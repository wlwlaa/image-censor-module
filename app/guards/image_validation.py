from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.schemas import CheckResult, Severity, Verdict


@dataclass(frozen=True)
class ValidatedImage:
    normalized_png: bytes
    original_filename: str
    detected_format: str
    width: int
    height: int
    metadata_text: str


class ImageValidationError(ValueError):
    pass


class ImageValidator:
    version = "pillow-1"
    allowed_formats = {"JPEG", "PNG", "WEBP"}
    allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
    format_content_types = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

    def __init__(self, max_upload_bytes: int, max_pixels: int) -> None:
        self._max_upload_bytes = max_upload_bytes
        self._max_pixels = max_pixels

    @property
    def max_upload_bytes(self) -> int:
        return self._max_upload_bytes

    def validate(
        self,
        content: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> tuple[ValidatedImage, CheckResult]:
        if not content:
            raise ImageValidationError("Image is empty")
        if len(content) > self._max_upload_bytes:
            raise ImageValidationError("Image exceeds upload size limit")
        if not content_type:
            raise ImageValidationError("MIME type is required")
        if content_type not in self.allowed_content_types:
            raise ImageValidationError(f"Unsupported MIME type: {content_type}")

        try:
            with Image.open(io.BytesIO(content)) as image:
                detected_format = image.format or ""
                if detected_format not in self.allowed_formats:
                    raise ImageValidationError(f"Unsupported image format: {detected_format or 'unknown'}")
                if content_type != self.format_content_types[detected_format]:
                    raise ImageValidationError("Declared MIME type does not match detected image format")
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > self._max_pixels:
                    raise ImageValidationError("Image exceeds pixel limit")
                metadata_text = " ".join(f"{key}={value}" for key, value in image.info.items())
                image.load()
                normalized = image.convert("RGB")
                output = io.BytesIO()
                normalized.save(output, format="PNG")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ImageValidationError("Invalid or unsafe image") from exc

        validated = ValidatedImage(
            normalized_png=output.getvalue(),
            original_filename=filename,
            detected_format=detected_format,
            width=width,
            height=height,
            metadata_text=metadata_text,
        )
        return validated, CheckResult(
            check="image_validation",
            verdict=Verdict.ALLOW,
            reason="Image validated and metadata stripped",
            details={"format": detected_format, "mime": content_type, "width": width, "height": height},
        )
