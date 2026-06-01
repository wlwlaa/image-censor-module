from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    hmac_secret: str
    max_upload_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 16_000_000
    policy_version: str = "mvp-1"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("GENSECOPS_DATA_DIR", "data")),
            hmac_secret=os.getenv("GENSECOPS_HMAC_SECRET") or secrets.token_hex(32),
            max_upload_bytes=int(os.getenv("GENSECOPS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)),
            max_pixels=int(os.getenv("GENSECOPS_MAX_PIXELS", 16_000_000)),
        )

