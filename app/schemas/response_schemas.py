from typing import Any

from pydantic import BaseModel


class AdversarialPerturbationResult(BaseModel):
    is_suspicious: bool
    score: float
    threshold: float
    method: str
    explanation: str
    features: dict[str, float]
    limitations: list[str]


class LlamaGuardResult(BaseModel):
    is_safe: bool
    verdict: str
    raw_response: str | None = None
    reason: str | None = None
    unsafe_reasons: list[str] | None = None
    unsafe_reason_details: list[dict[str, str]] | None = None
    provider: str
    model: str


class OCRBlock(BaseModel):
    text: str
    confidence: float
    bbox: list[list[float]] | None = None
    source: str | None = None
    rotation_angle: int | None = None


class OCRResult(BaseModel):
    has_text: bool
    text: str
    blocks: list[OCRBlock]
    error: str | None = None


class ModerationAnalysis(BaseModel):
    suspicious_perturbation: AdversarialPerturbationResult | dict[str, Any]
    ocr: OCRResult | None
    llama_guard: LlamaGuardResult | None


class ImageModerationResponse(BaseModel):
    status: str
    reason: str | None = None
    message: str
    filename: str | None
    content_type: str
    analysis: ModerationAnalysis


class LlamaGuardImageCheckResponse(BaseModel):
    status: str
    filename: str | None
    content_type: str
    llama_guard: LlamaGuardResult
