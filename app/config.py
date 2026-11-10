"""Application settings loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden by an env variable of the same name."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "call_results"
    mongodb_timeout_ms: int = Field(default=5000, ge=100)

    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    prefetch_count: int = Field(default=10, ge=1, le=1000)
    retry_delay_seconds: float = Field(default=1.0, ge=0)
    storage_retry_max_delay_seconds: float = Field(default=30.0, gt=0)
    reconnect_initial_delay_seconds: float = Field(default=1.0, gt=0)
    reconnect_max_delay_seconds: float = Field(default=30.0, gt=0)

    log_level: str = "INFO"
