import io

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from PIL import Image, UnidentifiedImageError

from app.schemas.response_schemas import (
    ImageModerationResponse,
    LlamaGuardImageCheckResponse,
)
from app.services.adversarial_detector import (
    LIMITATIONS,
    METHOD_NAME,
    SUSPICIOUS_THRESHOLD,
    detect_adversarial_perturbation,
)
from app.services.llama_guard_service import check_image_with_llama_guard
from app.services.ocr_service import extract_text_from_image


app = FastAPI(title="FastAPI Image Upload Service")


@app.get("/")
async def healthcheck() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "FastAPI Image Upload Service is running",
    }


async def _read_valid_image_file(
    file: UploadFile | None,
) -> tuple[bytes, Image.Image, str]:
    if file is None:
        raise HTTPException(status_code=400, detail="No file uploaded")

    if not file.content_type:
        raise HTTPException(status_code=400, detail="File content type is missing")

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file is not an image")

    file_bytes = await file.read()

    try:
        image = Image.open(io.BytesIO(file_bytes))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file")

    return file_bytes, image, file.content_type


def _failed_suspicious_detector_result(exc: Exception) -> dict:
    return {
        "is_suspicious": False,
        "score": 0.0,
        "threshold": SUSPICIOUS_THRESHOLD,
        "method": METHOD_NAME,
        "explanation": f"Suspicious perturbation check failed: {exc}",
        "features": {},
        "limitations": LIMITATIONS,
    }


def _build_unsafe_llama_guard_message(llama_guard_result: dict) -> str:
    unsafe_reasons = llama_guard_result.get("unsafe_reasons") or []
    reason = llama_guard_result.get("reason")

    if unsafe_reasons:
        reason_text = ", ".join(str(item) for item in unsafe_reasons)
        return (
            "Image rejected because Llama Guard classified it as unsafe. "
            f"Reasons: {reason_text}."
        )

    if reason:
        return (
            "Image rejected because Llama Guard classified it as unsafe. "
            f"Reason: {reason}."
        )

    return "Image rejected because Llama Guard classified it as unsafe."


@app.post("/upload-image")
async def upload_image(
    file: UploadFile | None = File(default=None),
) -> ImageModerationResponse:
    file_bytes, image, content_type = await _read_valid_image_file(file)

    try:
        suspicious_result = detect_adversarial_perturbation(image)
    except Exception as exc:
        suspicious_result = _failed_suspicious_detector_result(exc)

    if suspicious_result.get("is_suspicious") is True:
        return {
            "status": "rejected",
            "reason": "suspicious_perturbation_detected",
            "message": "Image rejected because suspicious perturbation-like patterns were detected.",
            "filename": file.filename,
            "content_type": content_type,
            "analysis": {
                "suspicious_perturbation": suspicious_result,
                "ocr": None,
                "llama_guard": None,
            },
        }

    try:
        ocr_result = extract_text_from_image(image)
    except Exception as exc:
        ocr_result = {
            "has_text": False,
            "text": "",
            "blocks": [],
            "error": f"OCR failed: {exc}",
        }

    llama_guard_result = await check_image_with_llama_guard(
        image_bytes=file_bytes,
        mime_type=content_type,
        ocr_text=str(ocr_result.get("text") or ""),
    )

    if llama_guard_result.get("verdict") == "error":
        return {
            "status": "rejected",
            "reason": "llama_guard_failed",
            "message": "Image rejected because Llama Guard safety check failed.",
            "filename": file.filename,
            "content_type": content_type,
            "analysis": {
                "suspicious_perturbation": suspicious_result,
                "ocr": ocr_result,
                "llama_guard": llama_guard_result,
            },
        }

    if llama_guard_result.get("is_safe") is not True:
        return {
            "status": "rejected",
            "reason": "unsafe_content_detected",
            "message": _build_unsafe_llama_guard_message(llama_guard_result),
            "filename": file.filename,
            "content_type": content_type,
            "analysis": {
                "suspicious_perturbation": suspicious_result,
                "ocr": ocr_result,
                "llama_guard": llama_guard_result,
            },
        }

    return {
        "status": "success",
        "reason": None,
        "message": "Image passed all checks and can be used.",
        "filename": file.filename,
        "content_type": content_type,
        "analysis": {
            "suspicious_perturbation": suspicious_result,
            "ocr": ocr_result,
            "llama_guard": llama_guard_result,
        },
    }


@app.post("/llama-guard/check-image")
async def check_image_with_llama_guard_endpoint(
    file: UploadFile | None = File(default=None),
    ocr_text: str | None = Form(default=None),
) -> LlamaGuardImageCheckResponse:
    file_bytes, _, content_type = await _read_valid_image_file(file)
    llama_guard_result = await check_image_with_llama_guard(
        image_bytes=file_bytes,
        mime_type=content_type,
        ocr_text=ocr_text or "",
    )

    return {
        "status": "success",
        "filename": file.filename,
        "content_type": content_type,
        "llama_guard": llama_guard_result,
    }
