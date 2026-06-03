from __future__ import annotations

import io
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

from app.config import ApiDemoSettings
from app.services.llama_guard import check_image_with_llama_guard
from app.services.ocr import extract_text_from_image
from app.services.perturbation import LIMITATIONS, METHOD_NAME, SUSPICIOUS_THRESHOLD, detect_adversarial_perturbation


router = APIRouter(tags=["api-demo"])


async def _read_valid_image_file(file: Optional[UploadFile]) -> tuple[bytes, Image.Image, str]:
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


def _unavailable_perturbation(exc: Exception) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": f"Perturbation detector unavailable: {exc}",
        "is_suspicious": False,
        "score": 0.0,
        "threshold": SUSPICIOUS_THRESHOLD,
        "method": METHOD_NAME,
        "features": {},
        "limitations": LIMITATIONS,
    }


def _unavailable_ocr(exc: Exception) -> dict[str, Any]:
    return {"status": "unavailable", "reason": f"OCR unavailable: {exc}", "has_text": False, "text": "", "blocks": []}


def _skipped_ocr(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason, "has_text": False, "text": "", "blocks": []}


def _unsafe_llama_guard_message(llama_guard_result: dict[str, Any]) -> str:
    unsafe_reasons = llama_guard_result.get("unsafe_reasons") or []
    if unsafe_reasons:
        return "Image rejected because Llama Guard classified it as unsafe. Reasons: " + ", ".join(str(item) for item in unsafe_reasons)
    if llama_guard_result.get("reason"):
        return f"Image rejected because Llama Guard classified it as unsafe. Reason: {llama_guard_result['reason']}"
    return "Image rejected because Llama Guard classified it as unsafe."


@router.post("/upload-image")
async def upload_image(file: Optional[UploadFile] = File(default=None)) -> dict[str, Any]:
    file_bytes, image, content_type = await _read_valid_image_file(file)

    try:
        suspicious_result = detect_adversarial_perturbation(image)
    except Exception as exc:
        suspicious_result = _unavailable_perturbation(exc)

    if suspicious_result.get("is_suspicious") is True:
        status, reason, message = (
            "rejected",
            "suspicious_perturbation_detected",
            "Image rejected because suspicious perturbation-like patterns were detected.",
        )
        ocr_result = None
        llama_guard_result = None
    else:
        api_settings = ApiDemoSettings.from_env()
        if not api_settings.openrouter_api_key:
            ocr_result = _skipped_ocr("OPENROUTER_API_KEY is not configured")
        else:
            try:
                ocr_result = extract_text_from_image(image)
            except Exception as exc:
                ocr_result = _unavailable_ocr(exc)

        llama_guard_result = await check_image_with_llama_guard(
            image_bytes=file_bytes,
            mime_type=content_type,
            ocr_text=str(ocr_result.get("text") or ""),
            settings=api_settings,
        )
        verdict = llama_guard_result.get("verdict")
        if verdict == "unavailable":
            status, reason, message = "unavailable", llama_guard_result.get("reason"), "Llama Guard is unavailable; base demo remains available."
        elif verdict == "error":
            status, reason, message = "rejected", "llama_guard_failed", "Image rejected because Llama Guard safety check failed."
        elif llama_guard_result.get("is_safe") is not True:
            status, reason, message = "rejected", "unsafe_content_detected", _unsafe_llama_guard_message(llama_guard_result)
        else:
            status, reason, message = "success", None, "Image passed all checks and can be used."

    return {
        "status": status,
        "reason": reason,
        "message": message,
        "final_decision": status,
        "filename": file.filename if file else None,
        "content_type": content_type,
        "analysis": {
            "suspicious_perturbation": suspicious_result,
            "ocr": ocr_result,
            "llama_guard": llama_guard_result,
        },
    }


@router.post("/llama-guard/check-image")
async def check_image_with_llama_guard_endpoint(
    file: Optional[UploadFile] = File(default=None),
    ocr_text: Optional[str] = Form(default=None),
) -> dict[str, Any]:
    file_bytes, _, content_type = await _read_valid_image_file(file)
    llama_guard_result = await check_image_with_llama_guard(
        image_bytes=file_bytes,
        mime_type=content_type,
        ocr_text=ocr_text or "",
    )
    if llama_guard_result.get("verdict") == "unavailable":
        return {"status": "unavailable", "reason": llama_guard_result.get("reason")}
    return {
        "status": "success",
        "filename": file.filename if file else None,
        "content_type": content_type,
        "llama_guard": llama_guard_result,
    }
