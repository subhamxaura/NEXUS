"""Central settings with fail-fast env validation (Phase 0)."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = Field(default="sqlite+aiosqlite:///./nexus_dev.db")
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default="dev-only-secret-change-me-32-chars!!")
    token_fernet_key: str = ""
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"
    analyzer_version: str = "v0.1.0"
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""
    llm_provider: str = "openai"
    llm_default_model: str = "gpt-4o-mini"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    llm_max_tokens: int = 4000
    llm_timeout_s: int = 120

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_len(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be >= 32 chars")
        return v


settings = Settings()
