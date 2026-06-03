from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from app.schemas import SafetyPassport, Verdict


class PassportService:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("HMAC secret must be at least 32 characters")
        self._secret = secret.encode("utf-8")

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def issue(
        self,
        *,
        artifact_id: str,
        content: bytes,
        policy_version: str,
        detector_versions: dict[str, str],
        verdict: Verdict,
    ) -> SafetyPassport:
        passport = SafetyPassport(
            artifact_id=artifact_id,
            sha256=self.sha256(content),
            policy_version=policy_version,
            detector_versions=detector_versions,
            verdict=verdict,
            timestamp=datetime.now(timezone.utc),
            signature="",
        )
        passport.signature = self._sign(passport)
        return passport

    def verify(self, passport: SafetyPassport, content: bytes, expected_artifact_id: str) -> bool:
        if passport.verdict != Verdict.ALLOW:
            return False
        if not hmac.compare_digest(passport.artifact_id, expected_artifact_id):
            return False
        if not hmac.compare_digest(passport.sha256, self.sha256(content)):
            return False
        return hmac.compare_digest(passport.signature, self._sign(passport))

    @staticmethod
    def digest(passport: SafetyPassport) -> str:
        return hashlib.sha256(passport.model_dump_json().encode("utf-8")).hexdigest()

    def _sign(self, passport: SafetyPassport) -> str:
        payload = passport.model_dump(mode="json", exclude={"signature"})
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
