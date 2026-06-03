from app.services.ocr_service import (
    _merge_ocr_blocks,
    _normalize_text,
    _parse_easyocr_results,
    _prepare_image_variants,
)
from PIL import Image


def test_normalize_text_collapses_whitespace() -> None:
    assert _normalize_text("  hello   world \n test ") == "hello world test"


def test_parse_easyocr_results_filters_low_confidence() -> None:
    results = [
        ([[0, 0], [10, 0], [10, 10], [0, 10]], "KEEP", 0.91),
        ([[0, 20], [10, 20], [10, 30], [0, 30]], "DROP", 0.1),
    ]

    blocks = _parse_easyocr_results(results, source="test")

    assert len(blocks) == 1
    assert blocks[0]["text"] == "KEEP"
    assert blocks[0]["confidence"] == 0.91
    assert blocks[0]["source"] == "test"


def test_merge_ocr_blocks_keeps_best_duplicate() -> None:
    blocks = _merge_ocr_blocks(
        [
            [
                {
                    "text": "STOP",
                    "confidence": 0.5,
                    "bbox": [[0, 0], [1, 0], [1, 1], [0, 1]],
                    "source": "variant_0",
                }
            ],
            [
                {
                    "text": "stop",
                    "confidence": 0.9,
                    "bbox": [[0, 0], [1, 0], [1, 1], [0, 1]],
                    "source": "variant_1",
                }
            ],
        ]
    )

    assert len(blocks) == 1
    assert blocks[0]["text"] == "stop"
    assert blocks[0]["confidence"] == 0.9


def test_prepare_image_variants_includes_rotation_sources() -> None:
    image = Image.new("RGB", (64, 64), color=(255, 255, 255))

    variants = _prepare_image_variants(image)
    sources = {variant["source"] for variant in variants}
    angles = {variant["angle"] for variant in variants}

    assert len(variants) == 4
    assert "rotated_ocr_upright" in sources
    assert "rotated_ocr_rotated_90" in sources
    assert "rotated_ocr_rotated_180" in sources
    assert "rotated_ocr_rotated_270" in sources
    assert 0 in angles
    assert 90 in angles
    assert 180 in angles
    assert 270 in angles
    assert 15 not in angles
    assert -15 not in angles
