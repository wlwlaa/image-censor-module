from typing import Any

import numpy as np
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


def _normalize_text(text: str) -> str:
    return " ".join(str(text).strip().split())


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


def _rotate_image(image: Image.Image, angle: int) -> Image.Image:
    if angle == 0:
        return image

    return image.rotate(angle, expand=True, fillcolor=(255, 255, 255))


def _build_rotated_variant(image: Image.Image, angle: int) -> dict[str, Any]:
    source_suffix = f"rotated_{angle}" if angle else "upright"

    return {
        "source": f"rotated_ocr_{source_suffix}",
        "angle": angle,
        "image": np.array(image),
    }


def _prepare_image_variants(image: Image.Image) -> list[dict[str, Any]]:
    rgb_image = _resize_for_ocr(image.convert("RGB"))
    variants: list[dict[str, Any]] = []

    for angle in ROTATION_ANGLES:
        rotated_image = _rotate_image(rgb_image, angle)
        variants.append(_build_rotated_variant(rotated_image, angle))

    return variants


def _extract_bbox(result: Any) -> list[list[float]]:
    bbox = result[0]
    return [[round(float(x), 2), round(float(y), 2)] for x, y in bbox]


def _bbox_top_left(block: dict[str, Any]) -> tuple[float, float]:
    bbox = block.get("bbox") or []
    if not bbox:
        return 0.0, 0.0

    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    return min(ys), min(xs)


def _parse_easyocr_results(
    results: list[Any],
    source: str,
    confidence_threshold: float = OCR_CONFIDENCE_THRESHOLD,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    for result in results:
        if len(result) < 3:
            continue

        _, text, confidence = result
        confidence = float(confidence)
        cleaned_text = _normalize_text(str(text))

        if confidence < confidence_threshold or not cleaned_text:
            continue

        blocks.append(
            {
                "text": cleaned_text,
                "confidence": round(confidence, 4),
                "bbox": _extract_bbox(result),
                "source": source,
            }
        )

    return blocks


def _merge_ocr_blocks(block_groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    best_by_text: dict[str, dict[str, Any]] = {}

    for blocks in block_groups:
        for block in blocks:
            key = block["text"].casefold()
            existing = best_by_text.get(key)
            if existing is None or block["confidence"] > existing["confidence"]:
                best_by_text[key] = block

    return sorted(best_by_text.values(), key=_bbox_top_left)


def extract_text_from_image(image: Image.Image) -> dict[str, Any]:
    reader = _get_reader()
    variants = _prepare_image_variants(image)
    block_groups: list[list[dict[str, Any]]] = []

    for variant in variants:
        results = reader.readtext(
            variant["image"],
            detail=1,
            paragraph=False,
            decoder="beamsearch",
            contrast_ths=0.1,
            adjust_contrast=0.7,
        )
        blocks = _parse_easyocr_results(results, source=variant["source"])
        for block in blocks:
            block["rotation_angle"] = variant["angle"]
        block_groups.append(blocks)

    blocks = _merge_ocr_blocks(block_groups)
    combined_text = "\n".join(block["text"] for block in blocks)

    return {
        "has_text": bool(blocks),
        "text": combined_text,
        "blocks": blocks,
    }
