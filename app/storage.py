from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.schemas import SafetyPassport


ARTIFACT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class LocalArtifactStorage:
    def __init__(self, data_dir: Path) -> None:
        self.quarantine_dir = data_dir / "quarantine"
        self.release_dir = data_dir / "release"
        self.audit_dir = data_dir / "audit"
        for directory in (self.quarantine_dir, self.release_dir, self.audit_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def quarantine(self, artifact_id: str, content: bytes) -> Path:
        self._validate_artifact_id(artifact_id)
        path = self.quarantine_dir / f"{artifact_id}.png"
        path.write_bytes(content)
        return path

    def promote(self, artifact_id: str, passport: SafetyPassport) -> Path:
        self._validate_artifact_id(artifact_id)
        source = self.quarantine_dir / f"{artifact_id}.png"
        destination = self.release_dir / f"{artifact_id}.png"
        shutil.copyfile(source, destination)
        passport_path = self.release_dir / f"{artifact_id}.passport.json"
        passport_path.write_text(passport.model_dump_json(indent=2), encoding="utf-8")
        return destination

    def load_release(self, artifact_id: str) -> tuple[Path, bytes, SafetyPassport]:
        self._validate_artifact_id(artifact_id)
        artifact_path = self.release_dir / f"{artifact_id}.png"
        passport_path = self.release_dir / f"{artifact_id}.passport.json"
        if not artifact_path.is_file() or not passport_path.is_file():
            raise FileNotFoundError(artifact_id)
        content = artifact_path.read_bytes()
        passport = SafetyPassport.model_validate(json.loads(passport_path.read_text(encoding="utf-8")))
        return artifact_path, content, passport

    @staticmethod
    def _validate_artifact_id(artifact_id: str) -> None:
        if not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
            raise ValueError("Invalid artifact ID")

