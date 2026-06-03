import math
from typing import Any

import cv2
import numpy as np
from PIL import Image


METHOD_NAME = "multi_feature_perturbation_heuristic"
SUSPICIOUS_THRESHOLD = 0.65
LIMITATIONS = [
    "This is a heuristic suspicious perturbation detector, not a definitive adversarial attack detector.",
    "A reliable adversarial attack detector usually requires a target model, clean reference images, or a trained detection model.",
    "High-frequency natural texture, text, compression artifacts, or camera noise may affect the score.",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default

    if math.isnan(result) or math.isinf(result):
        return default

    return result


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, _safe_float(value)))


def _normalize_log_scale(value: float, low: float, high: float) -> float:
    value = max(_safe_float(value), 0.0)
    low = max(_safe_float(low), 1e-6)
    high = max(_safe_float(high), low + 1e-6)

    if value <= low:
        return 0.0
    if value >= high:
        return 1.0

    normalized = (math.log1p(value) - math.log1p(low)) / (
        math.log1p(high) - math.log1p(low)
    )
    return _clamp01(normalized)


def _compute_laplacian_features(gray: np.ndarray) -> tuple[float, float]:
    if gray.size == 0:
        return 0.0, 0.0

    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    laplacian_score = _normalize_log_scale(laplacian_var, low=20.0, high=1200.0)
    return round(_safe_float(laplacian_var), 4), round(laplacian_score, 4)


def _compute_residual_score(gray: np.ndarray) -> tuple[float, float]:
    if gray.size == 0:
        return 0.0, 0.0

    gray_float = gray.astype(np.float32)
    blurred = cv2.GaussianBlur(gray_float, (5, 5), 0)
    residual = gray_float - blurred
    residual_energy = float(np.mean(np.abs(residual)))
    residual_score = _normalize_log_scale(residual_energy, low=1.0, high=18.0)
    return round(_safe_float(residual_energy), 4), round(residual_score, 4)


def _compute_color_inconsistency(rgb: np.ndarray) -> float:
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.size == 0:
        return 0.0

    rgb_float = rgb.astype(np.float32)
    channel_std = np.std(rgb_float, axis=2)
    if float(np.mean(channel_std)) < 1e-3:
        return 0.0

    residual_channels = []
    for channel_index in range(3):
        channel = rgb_float[:, :, channel_index]
        blurred = cv2.GaussianBlur(channel, (5, 5), 0)
        residual_channels.append(channel - blurred)

    residual_stack = np.stack(residual_channels, axis=2)
    inconsistency = float(np.mean(np.std(residual_stack, axis=2)))
    return round(_normalize_log_scale(inconsistency, low=0.4, high=8.0), 4)


def _compute_local_inconsistency(gray: np.ndarray, block_size: int = 32) -> float:
    height, width = gray.shape[:2]
    if height < 8 or width < 8:
        return 0.0

    size = max(8, min(block_size, height, width))
    gray_float = gray.astype(np.float32)
    blurred = cv2.GaussianBlur(gray_float, (5, 5), 0)
    residual = np.abs(gray_float - blurred)
    block_energies: list[float] = []

    for y in range(0, height, size):
        for x in range(0, width, size):
            block = residual[y : y + size, x : x + size]
            if block.size:
                block_energies.append(float(np.mean(block)))

    if len(block_energies) < 2:
        return 0.0

    energies = np.array(block_energies, dtype=np.float32)
    coefficient_of_variation = float(np.std(energies) / (np.mean(energies) + 1e-6))
    return round(_normalize_log_scale(coefficient_of_variation, low=0.15, high=1.6), 4)


def _compute_jpeg_blockiness(gray: np.ndarray) -> float:
    height, width = gray.shape[:2]
    if height < 16 or width < 16:
        return 0.0

    gray_float = gray.astype(np.float32)
    vertical_boundaries = np.arange(8, width, 8)
    horizontal_boundaries = np.arange(8, height, 8)

    boundary_diffs: list[np.ndarray] = []
    inner_diffs: list[np.ndarray] = []

    if vertical_boundaries.size:
        boundary_diffs.append(
            np.abs(gray_float[:, vertical_boundaries] - gray_float[:, vertical_boundaries - 1])
        )
        inner_columns = np.setdiff1d(np.arange(1, width), vertical_boundaries)
        if inner_columns.size:
            inner_diffs.append(
                np.abs(gray_float[:, inner_columns] - gray_float[:, inner_columns - 1])
            )

    if horizontal_boundaries.size:
        boundary_diffs.append(
            np.abs(gray_float[horizontal_boundaries, :] - gray_float[horizontal_boundaries - 1, :])
        )
        inner_rows = np.setdiff1d(np.arange(1, height), horizontal_boundaries)
        if inner_rows.size:
            inner_diffs.append(
                np.abs(gray_float[inner_rows, :] - gray_float[inner_rows - 1, :])
            )

    if not boundary_diffs or not inner_diffs:
        return 0.0

    boundary_mean = float(np.mean([np.mean(diff) for diff in boundary_diffs]))
    inner_mean = float(np.mean([np.mean(diff) for diff in inner_diffs]))
    blockiness_ratio = boundary_mean / (inner_mean + 1e-6)

    return round(_normalize_log_scale(blockiness_ratio, low=1.1, high=3.0), 4)


def detect_adversarial_perturbation(image: Image.Image) -> dict[str, Any]:
    rgb_image = image.convert("RGB")
    rgb = np.array(rgb_image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    laplacian_var, laplacian_score = _compute_laplacian_features(gray)
    residual_energy, residual_score = _compute_residual_score(gray)
    color_inconsistency_score = _compute_color_inconsistency(rgb)
    local_inconsistency_score = _compute_local_inconsistency(gray)
    jpeg_blockiness_score = _compute_jpeg_blockiness(gray)

    raw_score = (
        0.25 * laplacian_score
        + 0.30 * residual_score
        + 0.20 * color_inconsistency_score
        + 0.20 * local_inconsistency_score
        + 0.05 * jpeg_blockiness_score
    )

    if jpeg_blockiness_score > 0.6:
        raw_score *= 0.85

    score = round(_clamp01(raw_score), 4)
    is_suspicious = score >= SUSPICIOUS_THRESHOLD

    if is_suspicious:
        explanation = (
            "Suspicious perturbation-like patterns were detected. This may indicate "
            "adversarial perturbations, but it can also be caused by compression "
            "artifacts, natural high-frequency texture, text, sharpening, or sensor noise."
        )
    else:
        explanation = (
            "No strong suspicious perturbation-like patterns were detected. This does "
            "not prove the image is clean; it only means the heuristic did not find "
            "strong indicators."
        )

    return {
        "is_suspicious": is_suspicious,
        "score": score,
        "threshold": SUSPICIOUS_THRESHOLD,
        "method": METHOD_NAME,
        "explanation": explanation,
        "features": {
            "laplacian_variance": laplacian_var,
            "laplacian_score": laplacian_score,
            "high_frequency_residual_energy": residual_energy,
            "residual_score": residual_score,
            "color_inconsistency_score": color_inconsistency_score,
            "local_inconsistency_score": local_inconsistency_score,
            "jpeg_blockiness_score": jpeg_blockiness_score,
        },
        "limitations": LIMITATIONS,
    }
