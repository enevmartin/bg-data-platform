"""
Application configuration — all values driven by environment variables.
No hardcoded secrets or connection strings anywhere else in the codebase.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ───────────────────────────
    app_env: Literal["development", "production", "testing"] = "development"
    app_secret_key: str = "dev-insecure-key-change-in-production"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ── Database ──────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/platform.db"

    # ── Redis / Celery ────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # ── Storage paths ─────────────────────────
    data_dir: Path = Path("./data")
    raw_data_dir: Path = Path("./data/raw")
    processed_data_dir: Path = Path("./data/processed")

    # ── Scraper ───────────────────────────────
    scraper_user_agent: str = "bg-data-platform/1.0 (research crawler)"
    scraper_request_timeout: int = 30
    scraper_download_timeout: int = 300
    scraper_request_delay: float = 1.5
    scraper_max_retries: int = 5
    scraper_max_file_size_mb: int = 200

    # ── BNB ───────────────────────────────────
    bnb_base_url: str = "https://www.bnb.bg"
    bnb_statistics_path: str = "/en/Statistics/"

    # ── NSI ───────────────────────────────────
    nsi_base_url: str = "https://www.nsi.bg"
    nsi_statistics_path: str = "/en/content/"

    # ── Logging ───────────────────────────────
    log_level: str = "INFO"

    @field_validator("data_dir", "raw_data_dir", "processed_data_dir", mode="before")
    @classmethod
    def make_path(cls, v: str | Path) -> Path:
        return Path(v)

    def ensure_dirs(self) -> None:
        """Create storage directories if they don't exist."""
        for d in (self.data_dir, self.raw_data_dir, self.processed_data_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for Alembic and Celery tasks."""
        url = self.database_url
        if "sqlite+aiosqlite" in url:
            return url.replace("sqlite+aiosqlite", "sqlite")
        if "postgresql+asyncpg" in url:
            return url.replace("postgresql+asyncpg", "postgresql+psycopg2")
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
