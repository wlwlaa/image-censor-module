from __future__ import annotations

from typing import Any

from PIL import Image


OCR_CONFIDENCE_THRESHOLD = 0.3
OCR_LANGUAGES = ["en", "ru"]
MAX_OCR_IMAGE_SIDE = 1800
MIN_OCR_IMAGE_SIDE = 900
ROTATION_ANGLES = [0, 90, 180, 270]
_reader: Any | None = None


def _get_reader() -> Any:
    global _reader
    if _reader is None:
        import easyocr

        _reader = easyocr.Reader(OCR_LANGUAGES, gpu=False)
    return _reader


def _resize_for_ocr(image: Image.Image) -> Image.Image:
    width, height = image.size
    largest_side = max(width, height)
    smallest_side = min(width, height)
    if largest_side > MAX_OCR_IMAGE_SIDE:
        scale = MAX_OCR_IMAGE_SIDE / largest_side
    elif smallest_side < MIN_OCR_IMAGE_SIDE:
        scale = MIN_OCR_IMAGE_SIDE / max(smallest_side, 1)
    else:
        return image
    new_size = (max(int(width * scale), 1), max(int(height * scale), 1))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _prepare_image_variants(image: Image.Image) -> list[dict[str, Any]]:
    import numpy as np

    rgb_image = _resize_for_ocr(image.convert("RGB"))
    variants = []
    for angle in ROTATION_ANGLES:
        rotated = rgb_image if angle == 0 else rgb_image.rotate(angle, expand=True, fillcolor=(255, 255, 255))
        variants.append({"source": f"rotated_ocr_{'upright' if angle == 0 else f'rotated_{angle}'}", "angle": angle, "image": np.array(rotated)})
    return variants


def _parse_easyocr_results(results: list[Any], source: str) -> list[dict[str, Any]]:
    blocks = []
    for result in results:
        if len(result) < 3:
            continue
        bbox, text, confidence = result
        cleaned_text = " ".join(str(text).strip().split())
        if float(confidence) < OCR_CONFIDENCE_THRESHOLD or not cleaned_text:
            continue
        blocks.append(
            {
                "text": cleaned_text,
                "confidence": round(float(confidence), 4),
                "bbox": [[round(float(x), 2), round(float(y), 2)] for x, y in bbox],
                "source": source,
            }
        )
    return blocks


def _bbox_top_left(block: dict[str, Any]) -> tuple[float, float]:
    bbox = block.get("bbox") or []
    if not bbox:
        return 0.0, 0.0
    return min(point[1] for point in bbox), min(point[0] for point in bbox)


def extract_text_from_image(image: Image.Image) -> dict[str, Any]:
    reader = _get_reader()
    best_by_text: dict[str, dict[str, Any]] = {}
    for variant in _prepare_image_variants(image):
        results = reader.readtext(
            variant["image"],
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            contrast_ths=0.1,
            adjust_contrast=0.7,
        )
        for block in _parse_easyocr_results(results, source=variant["source"]):
            block["rotation_angle"] = variant["angle"]
            key = block["text"].casefold()
            existing = best_by_text.get(key)
            if existing is None or block["confidence"] > existing["confidence"]:
                best_by_text[key] = block

    blocks = sorted(best_by_text.values(), key=_bbox_top_left)
    return {"has_text": bool(blocks), "text": "\n".join(block["text"] for block in blocks), "blocks": blocks}
