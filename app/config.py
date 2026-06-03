from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


MIN_SECRET_LENGTH = 32


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    hmac_secret: str
    download_token: str
    max_upload_bytes: int = 10 * 1024 * 1024
    max_request_bytes: int = 12 * 1024 * 1024
    max_pixels: int = 16_000_000
    policy_version: str = "mvp-1"

    def __post_init__(self) -> None:
        if len(self.hmac_secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"GENSECOPS_HMAC_SECRET must be at least {MIN_SECRET_LENGTH} characters")
        if len(self.download_token) < MIN_SECRET_LENGTH:
            raise ValueError(f"GENSECOPS_DOWNLOAD_TOKEN must be at least {MIN_SECRET_LENGTH} characters")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("GENSECOPS_DATA_DIR", "data")),
            hmac_secret=os.getenv("GENSECOPS_HMAC_SECRET", ""),
            download_token=os.getenv("GENSECOPS_DOWNLOAD_TOKEN", ""),
            max_upload_bytes=int(os.getenv("GENSECOPS_MAX_UPLOAD_BYTES", 10 * 1024 * 1024)),
            max_request_bytes=int(os.getenv("GENSECOPS_MAX_REQUEST_BYTES", 12 * 1024 * 1024)),
            max_pixels=int(os.getenv("GENSECOPS_MAX_PIXELS", 16_000_000)),
        )


@dataclass(frozen=True)
class ApiDemoSettings:
    openrouter_api_key: str | None = None
    llama_guard_model: str = "meta-llama/llama-guard-4-12b"
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = "GenSecOps API Demo"
    llama_guard_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ApiDemoSettings":
        return cls(
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or None,
            llama_guard_model=os.getenv("LLAMA_GUARD_MODEL", "meta-llama/llama-guard-4-12b"),
            openrouter_base_url=os.getenv(
                "OPENROUTER_BASE_URL",
                "https://openrouter.ai/api/v1/chat/completions",
            ),
            openrouter_site_url=os.getenv("OPENROUTER_SITE_URL") or None,
            openrouter_app_name=os.getenv("OPENROUTER_APP_NAME") or "GenSecOps API Demo",
            llama_guard_timeout_seconds=float(os.getenv("LLAMA_GUARD_TIMEOUT_SECONDS", "30")),
        )
