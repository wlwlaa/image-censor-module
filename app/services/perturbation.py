from __future__ import annotations

import math
from typing import Any

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
    return default if math.isnan(result) or math.isinf(result) else result


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
    return _clamp01((math.log1p(value) - math.log1p(low)) / (math.log1p(high) - math.log1p(low)))


def detect_adversarial_perturbation(image: Image.Image) -> dict[str, Any]:
    import cv2
    import numpy as np

    rgb = np.array(image.convert("RGB"))
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray.size else 0.0
    laplacian_score = _normalize_log_scale(laplacian_var, low=20.0, high=1200.0)
    gray_float = gray.astype(np.float32)
    blurred = cv2.GaussianBlur(gray_float, (5, 5), 0)
    residual = gray_float - blurred
    residual_energy = float(np.mean(np.abs(residual))) if gray.size else 0.0
    residual_score = _normalize_log_scale(residual_energy, low=1.0, high=18.0)
    raw_score = 0.45 * laplacian_score + 0.55 * residual_score
    score = round(_clamp01(raw_score), 4)
    is_suspicious = score >= SUSPICIOUS_THRESHOLD
    return {
        "is_suspicious": is_suspicious,
        "score": score,
        "threshold": SUSPICIOUS_THRESHOLD,
        "method": METHOD_NAME,
        "explanation": (
            "Suspicious perturbation-like patterns were detected."
            if is_suspicious
            else "No strong suspicious perturbation-like patterns were detected."
        ),
        "features": {
            "laplacian_variance": round(_safe_float(laplacian_var), 4),
            "laplacian_score": round(laplacian_score, 4),
            "high_frequency_residual_energy": round(_safe_float(residual_energy), 4),
            "residual_score": round(residual_score, 4),
        },
        "limitations": LIMITATIONS,
    }
