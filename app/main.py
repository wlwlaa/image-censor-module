from __future__ import annotations

import hmac
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image

from app.audit import AuditLogger
from app.config import Settings
from app.guards.image_validation import ImageValidationError, ImageValidator, ValidatedImage
from app.guards.ocr_pii_guard import OcrPiiGuard
from app.guards.output_guard import MockOutputDetector, OutputDetector
from app.guards.prompt_guard import PromptGuard
from app.passport import PassportService
from app.policy_engine import PolicyEngine
from app.schemas import CheckResult, ModerationResponse, Severity, Verdict
from app.storage import LocalArtifactStorage


def create_app(
    settings: Settings | None = None,
    output_detector: OutputDetector | None = None,
    audit_logger: AuditLogger | None = None,
) -> FastAPI:
    app = FastAPI(title="GenSecOps Psys Image Guardrail", version="0.1.0")
    config = settings or Settings.from_env()
    storage = LocalArtifactStorage(config.data_dir)
    audit = audit_logger or AuditLogger(storage.audit_dir / "audit.jsonl")
    passport_service = PassportService(config.hmac_secret)
    prompt_guard = PromptGuard()
    image_validator = ImageValidator(config.max_upload_bytes, config.max_pixels)
    ocr_pii_guard = OcrPiiGuard()
    detector = output_detector or MockOutputDetector()
    policy_engine = PolicyEngine()
    detector_versions = {
        "prompt_guard": prompt_guard.version,
        "image_validator": image_validator.version,
        "ocr_pii_guard": ocr_pii_guard.version,
        "output_guard": detector.version,
    }

    @app.middleware("http")
    async def enforce_content_length(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/v1/moderate":
            content_length = request.headers.get("content-length")
            if not content_length or not content_length.isdigit():
                return JSONResponse(status_code=413, content={"detail": "Content-Length is required"})
            if int(content_length) > config.max_request_bytes:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/moderate", response_model=ModerationResponse)
    async def moderate(
        prompt: Annotated[str | None, Form()] = None,
        input_image: Annotated[UploadFile | None, File()] = None,
        generated_image: Annotated[UploadFile | None, File()] = None,
    ) -> ModerationResponse:
        request_id = uuid.uuid4().hex
        artifact_id: str | None = None
        hashes: dict[str, str] = {}
        checks: list[CheckResult] = []
        errors: list[str] = []

        if not any((prompt, input_image, generated_image)):
            raise HTTPException(status_code=422, detail="Provide prompt, input_image, or generated_image")

        if prompt:
            checks.append(prompt_guard.check(prompt))

        source_image: ValidatedImage | None = None
        if input_image:
            source_image = await validate_upload(
                input_image,
                validator=image_validator,
                checks=checks,
                errors=errors,
                hashes=hashes,
                sha256=passport_service.sha256,
                check_name="input_image_validation",
            )
            if source_image:
                checks.append(ocr_pii_guard.check(source_image))

        required_input_checks = {"input_image_validation", "ocr_pii_guard"} if input_image else set()
        pre_generation_decision = (
            policy_engine.evaluate(checks, required_checks=required_input_checks) if checks else None
        )
        if pre_generation_decision and pre_generation_decision.verdict != Verdict.ALLOW:
            return record_response(
                audit=audit,
                request_id=request_id,
                checks=checks,
                decision=pre_generation_decision,
                artifact_id=None,
                hashes=hashes,
                errors=errors,
                policy_version=policy_engine.version,
                detector_versions=detector_versions,
            )

        if generated_image:
            output_content = await generated_image.read(config.max_upload_bytes + 1)
            output_filename = generated_image.filename or "generated-image"
        else:
            output_content = mock_generate(prompt=prompt, source_image=source_image)
            output_filename = "mock-generated.png"

        artifact_id = uuid.uuid4().hex
        storage.quarantine(artifact_id, output_content)
        hashes["quarantine_sha256"] = passport_service.sha256(output_content)

        output_image = validate_bytes(
            output_content,
            filename=output_filename,
            content_type=generated_image.content_type if generated_image else "image/png",
            validator=image_validator,
            checks=checks,
            errors=errors,
            check_name="output_image_validation",
        )
        if output_image:
            # Store the stripped and normalized representation that was actually inspected.
            storage.quarantine(artifact_id, output_image.normalized_png)
            hashes["normalized_sha256"] = passport_service.sha256(output_image.normalized_png)
            try:
                checks.append(detector.check(output_image))
            except Exception as exc:  # Fail closed at the adapter boundary.
                errors.append(f"output_guard: {exc}")
                checks.append(error_check("output_guard", exc))

        required_output_checks = {"output_image_validation", "output_guard"} | required_input_checks
        decision = policy_engine.evaluate(checks, required_checks=required_output_checks)
        passport = None
        decision_audit_attempted = False
        if decision.verdict == Verdict.ALLOW and output_image:
            passport = passport_service.issue(
                artifact_id=artifact_id,
                content=output_image.normalized_png,
                policy_version=policy_engine.version,
                detector_versions=detector_versions,
                verdict=decision.verdict,
            )
            try:
                decision_audit_attempted = True
                append_decision_audit(
                    audit=audit,
                    request_id=request_id,
                    checks=checks,
                    decision=decision,
                    artifact_id=artifact_id,
                    hashes=hashes,
                    errors=errors,
                    policy_version=policy_engine.version,
                    detector_versions=detector_versions,
                    passport_digest=passport_service.digest(passport),
                )
                storage.promote(artifact_id, passport)
                audit.append(
                    {
                        "event": "artifact_released",
                        "request_id": request_id,
                        "artifact_id": artifact_id,
                        "timestamp": now_iso(),
                        "hash": passport.sha256,
                        "passport_digest": passport_service.digest(passport),
                    }
                )
            except Exception as exc:  # Never claim ALLOW if release promotion fails.
                storage.revoke(artifact_id)
                errors.append(f"release_pipeline: {exc}")
                checks.append(error_check("release_pipeline", exc))
                decision = policy_engine.evaluate(checks, required_checks=required_output_checks)
                passport = None
                try:
                    audit.append(
                        {
                            "event": "artifact_release_failed",
                            "request_id": request_id,
                            "artifact_id": artifact_id,
                            "timestamp": now_iso(),
                            "reason": str(exc),
                        }
                    )
                except Exception:
                    pass

        return record_response(
            audit=audit,
            request_id=request_id,
            checks=checks,
            decision=decision,
            artifact_id=artifact_id,
            hashes=hashes,
            errors=errors,
            passport=passport,
            policy_version=policy_engine.version,
            detector_versions=detector_versions,
            write_audit=passport is None and not decision_audit_attempted,
        )

    @app.get("/v1/download/{artifact_id}")
    def download(
        artifact_id: str,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        request_id = uuid.uuid4().hex
        expected_authorization = f"Bearer {config.download_token}"
        if not authorization or not hmac.compare_digest(authorization, expected_authorization):
            audit.append(
                {
                    "event": "download_denied",
                    "request_id": request_id,
                    "artifact_id": artifact_id,
                    "timestamp": now_iso(),
                    "reason": "Missing or invalid bearer token",
                }
            )
            raise HTTPException(
                status_code=401,
                detail="Missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            _, content, passport = storage.load_release(artifact_id)
        except (FileNotFoundError, ValueError):
            raise HTTPException(status_code=404, detail="Released artifact not found")

        if not passport_service.verify(passport, content, expected_artifact_id=artifact_id):
            audit.append(
                {
                    "event": "download_denied",
                    "request_id": request_id,
                    "artifact_id": artifact_id,
                    "timestamp": now_iso(),
                    "reason": "Passport signature or artifact hash mismatch",
                }
            )
            raise HTTPException(status_code=409, detail="Artifact integrity verification failed")

        audit.append(
            {
                "event": "download_allowed",
                "request_id": request_id,
                "artifact_id": artifact_id,
                "timestamp": now_iso(),
                "hash": passport.sha256,
            }
        )
        return Response(
            content=content,
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{artifact_id}.png"'},
        )

    return app


async def validate_upload(
    upload: UploadFile,
    *,
    validator: ImageValidator,
    checks: list[CheckResult],
    errors: list[str],
    hashes: dict[str, str],
    sha256,
    check_name: str,
) -> ValidatedImage | None:
    content = await upload.read(validator.max_upload_bytes + 1)
    hashes["input_file_hash"] = sha256(content)
    return validate_bytes(
        content,
        filename=upload.filename or "uploaded-image",
        content_type=upload.content_type,
        validator=validator,
        checks=checks,
        errors=errors,
        check_name=check_name,
    )


def validate_bytes(
    content: bytes,
    *,
    filename: str,
    content_type: str | None,
    validator: ImageValidator,
    checks: list[CheckResult],
    errors: list[str],
    check_name: str,
) -> ValidatedImage | None:
    try:
        image, result = validator.validate(content, filename, content_type)
        checks.append(result.model_copy(update={"check": check_name}))
        return image
    except ImageValidationError as exc:
        errors.append(f"{check_name}: {exc}")
        checks.append(error_check(check_name, exc))
        return None


def error_check(check_name: str, exc: Exception) -> CheckResult:
    return CheckResult(
        check=check_name,
        verdict=Verdict.BLOCK,
        categories=["internal_error"],
        severity=Severity.CRITICAL,
        reason=f"Fail closed: {check_name} failed",
        error=str(exc),
    )


def mock_generate(prompt: str | None, source_image: ValidatedImage | None) -> bytes:
    if source_image:
        return source_image.normalized_png
    image = Image.new("RGB", (256, 256), color=(242, 245, 249))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def record_response(
    *,
    audit: AuditLogger,
    request_id: str,
    checks: list[CheckResult],
    decision,
    artifact_id: str | None,
    hashes: dict[str, str],
    errors: list[str],
    passport=None,
    policy_version: str,
    detector_versions: dict[str, str],
    write_audit: bool = True,
) -> ModerationResponse:
    response = ModerationResponse(
        request_id=request_id,
        verdict=decision.verdict,
        categories=decision.categories,
        severity=decision.severity,
        reason=decision.reason,
        artifact_id=artifact_id,
        passport=passport,
        checks=checks,
        errors=errors,
    )
    if write_audit:
        append_decision_audit(
            audit=audit,
            request_id=request_id,
            checks=checks,
            decision=decision,
            artifact_id=artifact_id,
            hashes=hashes,
            errors=errors,
            policy_version=policy_version,
            detector_versions=detector_versions,
            passport_digest=PassportService.digest(passport) if passport else None,
        )
    return response


def append_decision_audit(
    *,
    audit: AuditLogger,
    request_id: str,
    checks: list[CheckResult],
    decision,
    artifact_id: str | None,
    hashes: dict[str, str],
    errors: list[str],
    policy_version: str,
    detector_versions: dict[str, str],
    passport_digest: str | None,
) -> None:
    audit.append(
        {
            "event": "moderation_decision",
            "request_id": request_id,
            "timestamp": now_iso(),
            "checks": [check.model_dump(mode="json") for check in checks],
            "verdict": decision.verdict,
            "categories": decision.categories,
            "severity": decision.severity,
            "reason": decision.reason,
            "artifact_id": artifact_id,
            "hashes": hashes,
            "errors": errors,
            "policy_version": policy_version,
            "detector_versions": detector_versions,
            "passport_digest": passport_digest,
        }
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
