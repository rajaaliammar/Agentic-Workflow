"""Pydantic Settings — environment-backed enterprise configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Active Groq production models (see https://console.groq.com/docs/models)
GROQ_MODEL_PRIMARY = "llama-3.3-70b-versatile"
GROQ_MODEL_FAST = "llama-3.1-8b-instant"

# Legacy / decommissioned model IDs → active replacements (applied on settings load)
DEPRECATED_GROQ_MODELS: dict[str, str] = {
    "llama-3.1-70b-versatile": GROQ_MODEL_PRIMARY,
    "llama-3.3-70b-specdec": GROQ_MODEL_PRIMARY,
    "llama3-70b-8192": GROQ_MODEL_PRIMARY,
    "llama3-8b-8192": GROQ_MODEL_FAST,
    "mixtral-8x7b-32768": GROQ_MODEL_PRIMARY,
    "gemma2-9b-it": GROQ_MODEL_FAST,
}


class Settings(BaseSettings):
    """Central configuration loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = Field(default="Agentic-Workflow", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    debug: bool = Field(default=False, alias="DEBUG")
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")

    # LLM provider (groq | openai)
    llm_provider: str = Field(default="groq", alias="LLM_PROVIDER")
    groq_api_key: SecretStr = Field(default=SecretStr(""), alias="GROQ_API_KEY")
    groq_model: str = Field(default=GROQ_MODEL_PRIMARY, alias="GROQ_MODEL")
    groq_model_fast: str = Field(default=GROQ_MODEL_FAST, alias="GROQ_MODEL_FAST")

    # OpenAI / LLM
    openai_api_key: SecretStr = Field(default=SecretStr(""), alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.3, alias="OPENAI_TEMPERATURE")

    # Firecrawl
    firecrawl_api_key: SecretStr = Field(default=SecretStr(""), alias="FIRECRAWL_API_KEY")

    # Gmail
    gmail_credentials_path: Path = Field(
        default=Path("credentials/credentials.json"),
        alias="GMAIL_CREDENTIALS_PATH",
    )
    gmail_token_path: Path = Field(
        default=Path("credentials/token.json"),
        alias="GMAIL_TOKEN_PATH",
    )
    gmail_sender_email: str = Field(default="", alias="GMAIL_SENDER_EMAIL")

    # Lead generation
    default_industry: str = Field(default="B2B SaaS", alias="DEFAULT_INDUSTRY")
    default_location: str = Field(default="United States", alias="DEFAULT_LOCATION")
    max_leads_per_run: int = Field(default=10, alias="MAX_LEADS_PER_RUN")
    scrape_timeout_seconds: int = Field(default=30, alias="SCRAPE_TIMEOUT_SECONDS")
    min_qualification_score: float = Field(default=6.0, alias="MIN_QUALIFICATION_SCORE")

    # Outreach
    outreach_from_name: str = Field(default="Your Name", alias="OUTREACH_FROM_NAME")
    outreach_from_company: str = Field(default="Your Company", alias="OUTREACH_FROM_COMPANY")
    outreach_framework: str = Field(default="PAS", alias="OUTREACH_FRAMEWORK")
    dry_run: bool = Field(default=True, alias="DRY_RUN")

    # HITL
    require_human_approval: bool = Field(default=True, alias="REQUIRE_HUMAN_APPROVAL")

    @field_validator("groq_model", "groq_model_fast", mode="before")
    @classmethod
    def remap_deprecated_groq_model(cls, value: object) -> str:
        """Rewrite decommissioned Groq model IDs to active production models."""
        if not isinstance(value, str) or not value.strip():
            return GROQ_MODEL_PRIMARY
        normalized = value.strip()
        replacement = DEPRECATED_GROQ_MODELS.get(normalized.lower())
        return replacement if replacement else normalized

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def active_llm_model(self) -> str:
        """Return the model name for the configured LLM provider."""
        if self.llm_provider.lower() == "groq":
            return self.groq_model
        return self.openai_model


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
