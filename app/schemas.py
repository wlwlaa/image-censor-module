from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class Severity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_ORDER = {
    Severity.NONE: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class CheckResult(BaseModel):
    check: str
    verdict: Verdict
    categories: list[str] = Field(default_factory=list)
    severity: Severity = Severity.NONE
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class PolicyDecision(BaseModel):
    verdict: Verdict
    categories: list[str] = Field(default_factory=list)
    severity: Severity
    reason: str


class SafetyPassport(BaseModel):
    artifact_id: str
    sha256: str
    policy_version: str
    detector_versions: dict[str, str]
    verdict: Verdict
    timestamp: datetime
    signature: str


class ModerationResponse(BaseModel):
    request_id: str
    verdict: Verdict
    categories: list[str]
    severity: Severity
    reason: str
    artifact_id: Optional[str] = None
    passport: Optional[SafetyPassport] = None
    checks: list[CheckResult]
    errors: list[str] = Field(default_factory=list)
