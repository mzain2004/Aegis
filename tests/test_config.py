"""Configuration tests for Veto Ops proxy Phase 1."""

from __future__ import annotations

from app.config import get_settings


def test_settings_load_defaults() -> None:
    settings = get_settings()

    assert settings.proxy_host == "0.0.0.0"
    assert settings.proxy_port == 9000
    assert settings.k8s_mcp_server_url.startswith("http")
    assert settings.nonce_ttl == 300
    assert settings.pending_request_ttl_seconds == 300
    assert settings.log_level in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
    assert settings.environment == "development"
