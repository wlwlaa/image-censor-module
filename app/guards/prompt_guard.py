from __future__ import annotations

import re
import unicodedata

from app.schemas import CheckResult, Severity, Verdict


class PromptGuard:
    version = "rules-1"

    _forbidden = {
        "explicit": "sexual_content",
        "gore": "graphic_violence",
        "violence": "graphic_violence",
        "fake passport": "fraud_document",
        "bank card": "payment_details",
        "phishing": "phishing_asset",
    }
    _bypass_markers = (
        re.compile(r"\b(?:bypass|jailbreak|ignore safety|disable filter)\b", re.IGNORECASE),
        re.compile(r"(?:\\u[0-9a-fA-F]{4}){2,}"),
        re.compile(r"[^\w\s]{6,}"),
    )

    def check(self, prompt: str) -> CheckResult:
        normalized = unicodedata.normalize("NFKC", prompt).casefold()
        categories = sorted({category for keyword, category in self._forbidden.items() if keyword in normalized})
        if categories:
            return CheckResult(
                check="prompt_guard",
                verdict=Verdict.BLOCK,
                categories=categories,
                severity=Severity.HIGH,
                reason="Prompt contains a forbidden content marker",
            )

        if any(pattern.search(normalized) for pattern in self._bypass_markers):
            return CheckResult(
                check="prompt_guard",
                verdict=Verdict.REVIEW,
                categories=["suspicious_bypass"],
                severity=Severity.MEDIUM,
                reason="Prompt contains a suspicious bypass marker",
            )

        return CheckResult(
            check="prompt_guard",
            verdict=Verdict.ALLOW,
            reason="Prompt rules passed",
        )

