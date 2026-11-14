from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ShopDesk API"
    environment: str = "development"  # development | test | production
    debug: bool = False

    database_url: str = "sqlite:///./shopdesk.db"

    # Comma-separated list of allowed origins for the frontend.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Admin endpoints (/api/admin/*) can wipe and regenerate data.
    # They are enabled by default in development. If ADMIN_TOKEN is set,
    # requests must send it in the X-Admin-Token header.
    admin_enabled: bool = True
    admin_token: str | None = None

    # Seed the database automatically on startup when it is empty.
    auto_seed: bool = True
    default_seed: int = 42

    # AI (Groq). The AI endpoints return 503 until GROQ_API_KEY is set.
    groq_api_key: str | None = None
    ai_model: str = "openai/gpt-oss-120b"
    ai_temperature: float = 0.2
    ai_max_tokens: int = 4096
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 2

    @property
    def ai_enabled(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
