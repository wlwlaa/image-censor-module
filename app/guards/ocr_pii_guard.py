from __future__ import annotations

import re

from app.guards.image_validation import ValidatedImage
from app.schemas import CheckResult, Severity, Verdict


class OcrPiiGuard:
    """MVP adapter: scans filename and metadata. Replace with an OCR engine in production."""

    version = "heuristics-1"
    _card_candidate = re.compile(r"(?:\d[ -]?){13,19}")
    _passport = re.compile(r"\b(?:passport|паспорт|series|серия)\b", re.IGNORECASE)
    _payment = re.compile(r"\b(?:iban|bic|swift|account|payment|card|счет|карта|реквизит)\b", re.IGNORECASE)
    _barcode = re.compile(r"\b(?:qr|qrcode|barcode|штрихкод)\b", re.IGNORECASE)

    def check(self, image: ValidatedImage) -> CheckResult:
        text = f"{image.original_filename} {image.metadata_text}"
        categories: set[str] = set()
        if self._passport.search(text):
            categories.add("pii_passport")
        if self._payment.search(text) or any(self._luhn(number) for number in self._numbers(text)):
            categories.add("payment_details")
        if self._barcode.search(text):
            categories.add("qr_or_barcode")

        if categories:
            return CheckResult(
                check="ocr_pii_guard",
                verdict=Verdict.BLOCK,
                categories=sorted(categories),
                severity=Severity.CRITICAL,
                reason="Potential PII, payment details, or barcode marker detected before provider call",
                details={"adapter": "filename-and-metadata-heuristics"},
            )

        return CheckResult(
            check="ocr_pii_guard",
            verdict=Verdict.ALLOW,
            reason="No PII markers detected by MVP adapter",
            details={"adapter": "filename-and-metadata-heuristics"},
        )

    def _numbers(self, text: str) -> list[str]:
        return [re.sub(r"\D", "", match.group()) for match in self._card_candidate.finditer(text)]

    @staticmethod
    def _luhn(number: str) -> bool:
        if not 13 <= len(number) <= 19:
            return False
        digits = [int(digit) for digit in number]
        checksum = 0
        parity = len(digits) % 2
        for index, digit in enumerate(digits):
            if index % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0

