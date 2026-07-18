"""Configuration tests for Aegis proxy Phase 1."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings


def test_settings_load_defaults() -> None:
    settings = get_settings()

    assert settings.proxy_host == "0.0.0.0"
    assert settings.proxy_port == 9000
    assert settings.k8s_mcp_server_url.startswith("http")
    assert settings.nonce_ttl == 300
    assert settings.pending_request_ttl_seconds == 300
    assert settings.log_level in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    assert settings.environment == "development"


def test_settings_rejects_default_admin_key_outside_development() -> None:
    with pytest.raises(ValidationError, match="DEFAULT_ADMIN_APIKEY"):
        Settings(environment="production")


def test_settings_allows_default_admin_key_in_development() -> None:
    settings = Settings(environment="development")

    assert settings.environment == "development"
    assert settings.default_admin_apikey == "admin-api-key-12345"


def test_settings_allows_custom_admin_key_in_production() -> None:
    settings = Settings(
        environment="production", default_admin_apikey="strong-unique-key"
    )

    assert settings.environment == "production"
    assert settings.default_admin_apikey == "strong-unique-key"
