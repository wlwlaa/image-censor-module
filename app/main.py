from __future__ import annotations

import hmac
import io
import json
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from app.audit import AuditLogger
from app.config import Settings
from app.guards.image_validation import ImageValidationError, ImageValidator, ValidatedImage
from app.guards.ocr_pii_guard import OcrPiiGuard
from app.guards.output_guard import MockOutputDetector, OutputDetector
from app.guards.prompt_guard import PromptGuard
from app.passport import PassportService
from app.policy_engine import PolicyEngine
from app.routers.api_demo import router as api_demo_router
from app.schemas import CheckResult, ModerationResponse, Severity, Verdict
from app.storage import LocalArtifactStorage


def create_app(
    settings: Optional[Settings] = None,
    output_detector: Optional[OutputDetector] = None,
    audit_logger: Optional[AuditLogger] = None,
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
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(api_demo_router)

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

    @app.get("/", include_in_schema=False)
    def demo_ui() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    async def run_moderation(
        prompt: Optional[str],
        input_image: Optional[Any],
        generated_image: Optional[Any],
    ) -> ModerationResponse:
        request_id = uuid.uuid4().hex
        artifact_id: Optional[str] = None
        hashes: dict[str, str] = {}
        checks: list[CheckResult] = []
        errors: list[str] = []

        if not any((prompt, input_image, generated_image)):
            raise HTTPException(status_code=422, detail="Provide prompt, input_image, or generated_image")

        if prompt:
            checks.append(prompt_guard.check(prompt))

        source_image: Optional[ValidatedImage] = None
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

    @app.post("/v1/moderate", response_model=ModerationResponse)
    async def moderate(
        prompt: Annotated[Optional[str], Form()] = None,
        input_image: Annotated[Optional[UploadFile], File()] = None,
        generated_image: Annotated[Optional[UploadFile], File()] = None,
    ) -> ModerationResponse:
        return await run_moderation(prompt=prompt, input_image=input_image, generated_image=generated_image)

    @app.get("/demo-dataset")
    def get_demo_dataset() -> dict[str, Any]:
        dataset_dir = demo_dataset_dir()
        cases = load_demo_manifest(dataset_dir)
        return {
            "count": len(cases),
            "cases": [public_demo_case(case, dataset_dir) for case in cases],
        }

    @app.post("/demo-dataset/upload")
    async def upload_demo_dataset(files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        dataset_dir = demo_dataset_dir()
        await save_demo_dataset_uploads(files, dataset_dir, max_file_bytes=config.max_upload_bytes)
        cases = load_demo_manifest(dataset_dir)
        validate_demo_manifest_files(cases, dataset_dir)
        return {
            "status": "success",
            "count": len(cases),
            "cases": [public_demo_case(case, dataset_dir) for case in cases],
        }

    @app.post("/demo-dataset/run")
    async def run_demo_dataset() -> dict[str, Any]:
        dataset_dir = demo_dataset_dir()
        cases = load_demo_manifest(dataset_dir)
        results = []

        for case in cases:
            expected = str(case.get("expected_decision", "")).upper()
            try:
                input_upload = build_demo_upload(case.get("input"), dataset_dir)
                generated_upload = build_demo_upload(case.get("generated"), dataset_dir)
                response = await run_moderation(
                    prompt=case.get("prompt"),
                    input_image=input_upload,
                    generated_image=generated_upload,
                )
                actual = response.verdict.value
                result = {
                    "id": case["id"],
                    "title": case["title"],
                    "expected_decision": expected,
                    "actual_decision": actual,
                    "passed": actual == expected,
                    "reason": response.reason,
                    "artifact_id": response.artifact_id,
                    "passport": response.passport.model_dump(mode="json") if response.passport else None,
                    "categories": list(response.categories) if response.categories else [],
                    "input_image": case.get("input"),
                    "generated_image": case.get("generated"),
                }
            except Exception as exc:
                result = {
                    "id": case.get("id", "unknown"),
                    "title": case.get("title", "Unknown case"),
                    "expected_decision": expected,
                    "actual_decision": "ERROR",
                    "passed": False,
                    "reason": str(exc),
                    "artifact_id": None,
                    "passport": None,
                    "categories": [],
                    "input_image": case.get("input"),
                    "generated_image": case.get("generated"),
                }
            results.append(result)

        return {
            "count": len(results),
            "passed": sum(1 for item in results if item["passed"]),
            "results": results,
        }

    @app.get("/demo-dataset/image/{filename:path}", include_in_schema=False)
    def demo_dataset_image(filename: str) -> Response:
        dataset_dir = demo_dataset_dir()
        resolved = resolve_demo_file(filename, dataset_dir)
        if not resolved.exists() or not resolved.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        content_type = mimetypes.guess_type(resolved.name)[0] or "image/png"
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Not an image file")
        return Response(content=resolved.read_bytes(), media_type=content_type)

    @app.get("/v1/download/{artifact_id}")
    def download(
        artifact_id: str,
        authorization: Annotated[Optional[str], Header()] = None,
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


class InMemoryUpload:
    def __init__(self, *, filename: str, content_type: str, content: bytes) -> None:
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return self._content
        return self._content[:size]


def demo_dataset_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "demo_dataset"


async def save_demo_dataset_uploads(
    files: list[UploadFile],
    dataset_dir: Path,
    *,
    max_file_bytes: int,
) -> None:
    if not files:
        raise HTTPException(status_code=400, detail="Upload manifest.json and dataset images")

    dataset_dir.mkdir(parents=True, exist_ok=True)
    upload_names = [upload.filename or "" for upload in files]
    common_root = demo_upload_common_root(upload_names)
    saved_manifest = False

    for upload in files:
        relative = resolve_demo_upload_path(upload.filename or "", dataset_dir, common_root)
        if relative.suffix.lower() not in {".json", ".png", ".jpg", ".jpeg"}:
            raise HTTPException(status_code=400, detail=f"Unsupported dataset file type: {relative.name}")
        if relative.suffix.lower() == ".json" and relative.name != "manifest.json":
            raise HTTPException(status_code=400, detail="Only manifest.json is allowed as a JSON dataset file")

        content = await upload.read(max_file_bytes + 1)
        if len(content) > max_file_bytes:
            raise HTTPException(status_code=413, detail=f"Dataset file is too large: {relative.name}")

        target = dataset_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        saved_manifest = saved_manifest or relative.name == "manifest.json"

    if not saved_manifest:
        raise HTTPException(status_code=400, detail="Uploaded dataset must include manifest.json")


def demo_upload_common_root(names: list[str]) -> Optional[str]:
    parts = [Path(name).parts for name in names if name]
    if not parts or any(len(item) < 2 for item in parts):
        return None
    first = parts[0][0]
    if first == "demo_dataset":
        return None
    if all(item[0] == first for item in parts):
        return first
    return None


def resolve_demo_upload_path(raw_path: str, dataset_dir: Path, common_root: Optional[str]) -> Path:
    if not raw_path.strip():
        raise HTTPException(status_code=400, detail="Dataset upload filename is empty")

    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="Dataset upload path must stay inside demo_dataset/")
    if relative.parts and relative.parts[0] == "demo_dataset":
        relative = Path(*relative.parts[1:])
    elif common_root and relative.parts and relative.parts[0] == common_root:
        relative = Path(*relative.parts[1:])
    if not relative.parts:
        raise HTTPException(status_code=400, detail="Dataset upload path is invalid")

    target = (dataset_dir / relative).resolve()
    resolved_dataset_dir = dataset_dir.resolve()
    if target != resolved_dataset_dir and resolved_dataset_dir not in target.parents:
        raise HTTPException(status_code=400, detail="Dataset upload path escapes demo_dataset/")
    return relative


def load_demo_manifest(dataset_dir: Path) -> list[dict[str, Any]]:
    manifest_path = dataset_dir / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="demo_dataset/manifest.json not found")

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid demo_dataset/manifest.json: {exc}") from exc

    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="demo_dataset/manifest.json must contain a JSON array")

    cases = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"Dataset case #{index} must be an object")
        if not item.get("id") or not item.get("title") or not item.get("expected_decision"):
            raise HTTPException(status_code=400, detail=f"Dataset case #{index} is missing id, title, or expected_decision")
        if not item.get("input") and not item.get("generated") and not item.get("prompt"):
            raise HTTPException(status_code=400, detail=f"Dataset case {item['id']} has no input, generated, or prompt")
        cases.append(item)
    return cases


def validate_demo_manifest_files(cases: list[dict[str, Any]], dataset_dir: Path) -> None:
    for case in cases:
        for field in ("input", "generated"):
            raw_path = case.get(field)
            if not raw_path:
                continue
            path = resolve_demo_file(raw_path, dataset_dir)
            if not path.exists() or not path.is_file():
                raise HTTPException(status_code=400, detail=f"Dataset file not found: {raw_path}")


def public_demo_case(case: dict[str, Any], dataset_dir: Path) -> dict[str, Any]:
    return {
        "id": case["id"],
        "title": case["title"],
        "input": case.get("input"),
        "generated": case.get("generated"),
        "expected_decision": str(case["expected_decision"]).upper(),
        "description": case.get("description", ""),
        "input_exists": demo_file_exists(case.get("input"), dataset_dir),
        "generated_exists": demo_file_exists(case.get("generated"), dataset_dir),
    }


def demo_file_exists(raw_path: Optional[str], dataset_dir: Path) -> bool:
    if not raw_path:
        return False
    try:
        return resolve_demo_file(raw_path, dataset_dir).exists()
    except HTTPException:
        return False


def build_demo_upload(raw_path: Optional[str], dataset_dir: Path) -> Optional[InMemoryUpload]:
    if not raw_path:
        return None
    path = resolve_demo_file(raw_path, dataset_dir)
    if not path.exists() or not path.is_file():
        raise ValueError(f"Dataset file not found: {raw_path}")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise ValueError(f"Dataset file is not an image: {raw_path}")
    return InMemoryUpload(filename=path.name, content_type=content_type, content=path.read_bytes())


def resolve_demo_file(raw_path: str, dataset_dir: Path) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise HTTPException(status_code=400, detail="Dataset file path must be a non-empty string")

    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise HTTPException(status_code=400, detail="Dataset file path must stay inside demo_dataset/")

    if relative.parts and relative.parts[0] == "demo_dataset":
        candidate = dataset_dir.parent / relative
    else:
        candidate = dataset_dir / relative

    resolved_dataset_dir = dataset_dir.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_dataset_dir and resolved_dataset_dir not in resolved.parents:
        raise HTTPException(status_code=400, detail="Dataset file path escapes demo_dataset/")
    return resolved


async def validate_upload(
    upload: UploadFile,
    *,
    validator: ImageValidator,
    checks: list[CheckResult],
    errors: list[str],
    hashes: dict[str, str],
    sha256,
    check_name: str,
) -> Optional[ValidatedImage]:
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
    content_type: Optional[str],
    validator: ImageValidator,
    checks: list[CheckResult],
    errors: list[str],
    check_name: str,
) -> Optional[ValidatedImage]:
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


def mock_generate(prompt: Optional[str], source_image: Optional[ValidatedImage]) -> bytes:
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
    artifact_id: Optional[str],
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
    artifact_id: Optional[str],
    hashes: dict[str, str],
    errors: list[str],
    policy_version: str,
    detector_versions: dict[str, str],
    passport_digest: Optional[str],
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
    return datetime.now(timezone.utc).isoformat()
