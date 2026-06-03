import math

import numpy as np
from PIL import Image, ImageDraw

from app.services.adversarial_detector import detect_adversarial_perturbation


def _assert_valid_result(result: dict) -> None:
    assert isinstance(result["is_suspicious"], bool)
    assert 0.0 <= result["score"] <= 1.0
    assert math.isfinite(result["score"])
    assert result["method"] == "multi_feature_perturbation_heuristic"
    assert "features" in result
    assert "limitations" in result

    for value in result["features"].values():
        assert math.isfinite(value)


def test_smooth_image_has_low_score() -> None:
    image = Image.new("RGB", (128, 128), color=(128, 128, 128))

    result = detect_adversarial_perturbation(image)

    _assert_valid_result(result)
    assert result["is_suspicious"] is False
    assert result["score"] < 0.25


def test_random_noise_scores_higher_than_smooth_image() -> None:
    rng = np.random.default_rng(42)
    smooth_image = Image.new("RGB", (128, 128), color=(128, 128, 128))
    noise_array = rng.integers(0, 256, size=(128, 128, 3), dtype=np.uint8)
    noise_image = Image.fromarray(noise_array, mode="RGB")

    smooth_result = detect_adversarial_perturbation(smooth_image)
    noise_result = detect_adversarial_perturbation(noise_image)

    _assert_valid_result(noise_result)
    assert noise_result["score"] > smooth_result["score"]


def test_text_like_edges_do_not_break_detector() -> None:
    image = Image.new("RGB", (192, 96), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 70, 35), fill=(0, 0, 0))
    draw.rectangle((20, 45, 110, 60), fill=(0, 0, 0))
    draw.line((130, 20, 170, 70), fill=(0, 0, 0), width=5)

    result = detect_adversarial_perturbation(image)

    _assert_valid_result(result)
    assert result["score"] < 0.95
    assert result["features"]


def test_small_image_returns_valid_result() -> None:
    image = Image.new("RGB", (16, 16), color=(64, 128, 192))

    result = detect_adversarial_perturbation(image)

    _assert_valid_result(result)


def test_rgb_channel_perturbation_increases_color_inconsistency() -> None:
    rng = np.random.default_rng(7)
    clean = np.full((128, 128, 3), 128, dtype=np.uint8)
    perturbed = clean.copy()
    red_noise = rng.integers(-35, 36, size=(128, 128), dtype=np.int16)
    perturbed[:, :, 0] = np.clip(perturbed[:, :, 0].astype(np.int16) + red_noise, 0, 255)

    clean_result = detect_adversarial_perturbation(Image.fromarray(clean, mode="RGB"))
    perturbed_result = detect_adversarial_perturbation(Image.fromarray(perturbed, mode="RGB"))

    _assert_valid_result(perturbed_result)
    assert (
        perturbed_result["features"]["color_inconsistency_score"]
        > clean_result["features"]["color_inconsistency_score"]
    )
