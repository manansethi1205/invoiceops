from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://invoiceops:invoiceops@localhost:5432/invoiceops"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_access_key_id: str = "invoiceops"
    s3_secret_access_key: str = "invoiceops-local-only"
    s3_bucket: str = "invoice-documents"
    s3_region: str = "us-east-1"
    s3_server_side_encryption: str | None = None
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
