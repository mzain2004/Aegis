"""Application configuration for Aegis.

The settings model is intentionally small for Phase 1 and only validates the
foundation required to bootstrap the service.

TODO: add phase-specific runtime toggles for request inspection, approval,
and upstream forwarding behavior when those features are introduced.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Pydantic settings model for the Aegis proxy service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    proxy_host: str = Field(default="0.0.0.0", validation_alias="PROXY_HOST")
    proxy_port: int = Field(default=9000, validation_alias="PROXY_PORT")
    k8s_mcp_server_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="K8S_MCP_SERVER_URL",
    )
    shared_hmac_secret: str = Field(
        default="development-shared-secret",
        validation_alias="SHARED_HMAC_SECRET",
    )
    nonce_ttl: int = Field(default=300, validation_alias="NONCE_TTL")
    pending_request_ttl_seconds: int = Field(
        default=300,
        validation_alias="PENDING_REQUEST_TTL_SECONDS",
    )
    execution_backend: str = Field(
        default="kubernetes",
        validation_alias="EXECUTION_BACKEND",
    )
    execution_timeout_seconds: int = Field(
        default=10,
        validation_alias="EXECUTION_TIMEOUT",
    )
    execution_retries: int = Field(
        default=0,
        validation_alias="EXECUTION_RETRIES",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    database_url: str = Field(
        default="sqlite:///./aegis.db",
        validation_alias="DATABASE_URL",
    )
    auth_enabled: bool = Field(default=True, validation_alias="AUTH_ENABLED")
    allow_anonymous_dev: bool = Field(
        default=False, validation_alias="ALLOW_ANONYMOUS_DEV"
    )
    default_admin_username: str = Field(
        default="admin", validation_alias="DEFAULT_ADMIN_USERNAME"
    )
    default_admin_apikey: str = Field(
        default="admin-api-key-12345", validation_alias="DEFAULT_ADMIN_APIKEY"
    )
    prometheus_enabled: bool = Field(
        default=True, validation_alias="PROMETHEUS_ENABLED"
    )
    otel_enabled: bool = Field(default=False, validation_alias="OTEL_ENABLED")
    metrics_enabled: bool = Field(default=True, validation_alias="METRICS_ENABLED")
    audit_retention_days: int = Field(
        default=30, validation_alias="AUDIT_RETENTION_DAYS"
    )
    enable_trace: bool = Field(default=True, validation_alias="ENABLE_TRACE")
    health_check_timeout: int = Field(
        default=5, validation_alias="HEALTH_CHECK_TIMEOUT"
    )

    @field_validator("proxy_host")
    @classmethod
    def validate_proxy_host(cls, value: str) -> str:
        """Ensure the bind host is present and normalized."""

        host = value.strip()
        if not host:
            raise ValueError("PROXY_HOST must not be empty")
        return host

    @field_validator("proxy_port")
    @classmethod
    def validate_proxy_port(cls, value: int) -> int:
        """Keep the listening port inside the TCP range."""

        if not 1 <= value <= 65535:
            raise ValueError("PROXY_PORT must be between 1 and 65535")
        return value

    @field_validator("k8s_mcp_server_url")
    @classmethod
    def validate_k8s_mcp_server_url(cls, value: str) -> str:
        """Require a well-formed HTTP or HTTPS upstream URL."""

        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("K8S_MCP_SERVER_URL must be a valid http or https URL")
        return value.strip()

    @field_validator("shared_hmac_secret")
    @classmethod
    def validate_shared_hmac_secret(cls, value: str) -> str:
        """Keep the future HMAC secret non-empty and minimally strong."""

        secret = value.strip()
        if len(secret) < 16:
            raise ValueError("SHARED_HMAC_SECRET must be at least 16 characters")
        return secret

    @field_validator("nonce_ttl")
    @classmethod
    def validate_nonce_ttl(cls, value: int) -> int:
        """Ensure the future nonce window remains positive."""

        if value <= 0:
            raise ValueError("NONCE_TTL must be greater than zero")
        return value

    @field_validator("pending_request_ttl_seconds")
    @classmethod
    def validate_pending_request_ttl_seconds(cls, value: int) -> int:
        """Ensure suspended requests cannot expire immediately."""

        if value <= 0:
            raise ValueError("PENDING_REQUEST_TTL_SECONDS must be greater than zero")
        return value

    @field_validator("execution_backend")
    @classmethod
    def validate_execution_backend(cls, value: str) -> str:
        """Normalize the configured execution backend name."""

        backend = value.strip().lower()
        if not backend:
            raise ValueError("EXECUTION_BACKEND must not be empty")
        return backend

    @field_validator("execution_timeout_seconds")
    @classmethod
    def validate_execution_timeout_seconds(cls, value: int) -> int:
        """Keep execution timeouts positive."""

        if value <= 0:
            raise ValueError("EXECUTION_TIMEOUT must be greater than zero")
        return value

    @field_validator("execution_retries")
    @classmethod
    def validate_execution_retries(cls, value: int) -> int:
        """Keep retry budget non-negative."""

        if value < 0:
            raise ValueError("EXECUTION_RETRIES must be zero or greater")
        return value

    mcp_timeout_seconds: int = Field(default=10, validation_alias="MCP_TIMEOUT_SECONDS")

    @field_validator("mcp_timeout_seconds")
    @classmethod
    def validate_mcp_timeout_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MCP_TIMEOUT_SECONDS must be greater than zero")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Normalize and constrain the log level to common logging values."""

        normalized = value.strip().upper()
        allowed_levels = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed_levels:
            raise ValueError(
                "LOG_LEVEL must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG"
            )
        return normalized

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        """Normalize the deployment environment label."""

        environment = value.strip().lower()
        if not environment:
            raise ValueError("ENVIRONMENT must not be empty")
        return environment


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""

    return Settings()
