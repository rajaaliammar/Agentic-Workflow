"""Pydantic Settings — environment-backed enterprise configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    outreach_framework: Literal["PAS", "AIDA"] = Field(default="PAS", alias="OUTREACH_FRAMEWORK")
    dry_run: bool = Field(default=True, alias="DRY_RUN")

    # HITL
    require_human_approval: bool = Field(default=True, alias="REQUIRE_HUMAN_APPROVAL")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
