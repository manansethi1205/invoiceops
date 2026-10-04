from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    auth_mode: Literal["development", "oidc"] = "development"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_roles_claim: str = "roles"
    oidc_jwks_ttl_seconds: int = Field(default=300, ge=30, le=3600)
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
    vlm_enabled: bool = False
    supporting_vlm_enabled: bool = False
    supporting_vlm_provider: str = "openai"
    supporting_vlm_model: str = ""
    vlm_provider: str = "openai"
    vlm_model: str = ""
    vlm_prompt_version: str = "invoice-vision-v1"
    vlm_timeout_seconds: float = Field(default=45.0, gt=0)
    vlm_max_retries: int = Field(default=2, ge=0, le=5)
    vlm_max_pages: int = Field(default=5, gt=0, le=25)
    vlm_render_dpi: int = Field(default=150, ge=72, le=300)
    vlm_max_image_dimension: int = Field(default=2048, ge=512, le=4096)
    vlm_image_detail: str = "auto"
    vlm_fuzzy_grounding_threshold: float = Field(default=92.0, ge=0, le=100)
    openai_api_key: SecretStr | None = None
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4318", min_length=1, max_length=2048
    )
    otel_service_name: str = Field(default="invoiceops-api", min_length=1, max_length=100)
    otel_export_interval_seconds: int = Field(default=10, ge=1, le=300)
    request_id_header: str = Field(
        default="X-Request-ID", pattern=r"^[A-Za-z0-9-]+$", min_length=1, max_length=100
    )
    sse_poll_interval_seconds: float = Field(default=0.5, ge=0.1, le=5)
    sse_heartbeat_seconds: int = Field(default=15, ge=5, le=60)
    sse_batch_size: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def validate_vlm_configuration(self) -> "Settings":
        if self.environment.casefold() == "production" and self.auth_mode != "oidc":
            raise ValueError("production requires OIDC authentication")
        if self.auth_mode == "oidc":
            if not self.oidc_issuer or not self.oidc_audience:
                raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required")
            if not self.oidc_issuer.startswith("https://") and not (
                self.environment.casefold() != "production"
                and self.oidc_issuer.startswith("http://localhost:")
            ):
                raise ValueError("OIDC_ISSUER must use HTTPS outside local development")
            if not self.oidc_roles_claim.isidentifier():
                raise ValueError("OIDC_ROLES_CLAIM must be a simple claim name")
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint.startswith(
            ("http://", "https://")
        ):
            raise ValueError("OTEL_EXPORTER_OTLP_ENDPOINT must be an HTTP(S) endpoint")
        if self.supporting_vlm_enabled:
            if not self.supporting_vlm_model.strip():
                raise ValueError("SUPPORTING_VLM_MODEL must be configured when enabled")
            if self.supporting_vlm_provider not in {"openai", "fake", "replay"}:
                raise ValueError("SUPPORTING_VLM_PROVIDER is unsupported")
            if self.supporting_vlm_provider == "openai" and self.openai_api_key is None:
                raise ValueError("OpenAI credentials are required for supporting VLM")
        if not self.vlm_enabled:
            return self
        if not self.vlm_model.strip():
            raise ValueError("VLM_MODEL must be configured when VLM is enabled")
        if self.vlm_provider == "openai" and self.openai_api_key is None:
            raise ValueError(
                "OpenAI credentials must be configured when its VLM provider is enabled"
            )
        if self.vlm_provider not in {"openai", "fake", "replay"}:
            raise ValueError("VLM_PROVIDER is unsupported")
        if self.vlm_image_detail not in {"low", "high", "auto", "original"}:
            raise ValueError("VLM_IMAGE_DETAIL is unsupported")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
