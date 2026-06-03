from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openrouter_api_key: str | None = None
    llama_guard_model: str = "meta-llama/llama-guard-4-12b"
    openrouter_base_url: str = "https://openrouter.ai/api/v1/chat/completions"
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = "FastAPI Image Moderation Service"
    llama_guard_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
