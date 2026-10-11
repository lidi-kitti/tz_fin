from functools import lru_cache

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://payments:payments@localhost:5432/payments"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    api_key: str = "dev-api-key-change-me"

    payment_success_rate: float = Field(default=0.9, ge=0.0, le=1.0)
    gateway_delay_min: float = Field(default=2.0, ge=0.0)
    gateway_delay_max: float = Field(default=5.0, ge=0.0)
    max_attempts: int = Field(default=3, ge=1)
    webhook_timeout_seconds: float = Field(default=10.0, gt=0)
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0)
    outbox_batch_size: int = Field(default=50, ge=1)
    enable_outbox_worker: bool = True

    @field_validator("gateway_delay_max")
    @classmethod
    def delay_range_is_valid(cls, value: float, info: ValidationInfo) -> float:
        minimum = info.data.get("gateway_delay_min", 0.0)
        if value < minimum:
            raise ValueError("GATEWAY_DELAY_MAX must be >= GATEWAY_DELAY_MIN")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
