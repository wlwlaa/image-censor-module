from __future__ import annotations

from typing import Protocol

from app.guards.image_validation import ValidatedImage
from app.schemas import CheckResult, Severity, Verdict


class OutputDetector(Protocol):
    version: str

    def check(self, image: ValidatedImage) -> CheckResult: ...


class MockOutputDetector:
    """Deterministic demo detector. Replace with a validated model adapter."""

    version = "mock-1"
    _markers = {
        "violence": ("graphic_violence", Severity.HIGH),
        "gore": ("graphic_violence", Severity.HIGH),
        "unsafe": ("unsafe_content", Severity.HIGH),
        "pii": ("pii", Severity.CRITICAL),
    }

    def check(self, image: ValidatedImage) -> CheckResult:
        haystack = f"{image.original_filename} {image.metadata_text}".casefold()
        if "detector_error" in haystack:
            raise RuntimeError("Simulated output detector failure")

        categories = sorted({category for marker, (category, _) in self._markers.items() if marker in haystack})
        if categories:
            severity = max(
                (severity for marker, (_, severity) in self._markers.items() if marker in haystack),
                key=lambda item: list(Severity).index(item),
            )
            return CheckResult(
                check="output_guard",
                verdict=Verdict.BLOCK,
                categories=categories,
                severity=severity,
                reason="Mock output detector found an unsafe filename or metadata marker",
                details={"detector": self.version},
            )

        return CheckResult(
            check="output_guard",
            verdict=Verdict.ALLOW,
            reason="Mock output detector passed",
            details={"detector": self.version},
        )

