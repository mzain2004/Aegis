"""Dependency injection helpers for the FastAPI application."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from app.config import Settings
from app.config import get_settings as load_settings
from app.execution.base import ExecutionEngine
from app.execution.factory import ExecutionFactory
from app.forwarder import MCPForwarder
from app.logger import get_logger as build_logger
from app.pending_store import PendingRequestStore


def get_settings() -> Settings:
    """Return the cached application settings."""

    return load_settings()


def get_logger(name: str = "aegis") -> Any:
    """Return a structured logger for dependency injection."""

    return build_logger(name)


def get_forwarder(
    settings: Annotated[Settings, Depends(load_settings)],
) -> MCPForwarder:
    """Dependency that instantiates an `MCPForwarder` configured from settings.

    A new forwarder (and its underlying client when created) is returned for
    each request to keep lifetime simple and testable. Tests may override this
    dependency to inject a mock or a client with a MockTransport.
    """

    return MCPForwarder(settings=settings)


@lru_cache(maxsize=1)
def get_pending_store() -> PendingRequestStore:
    """Return the application-lifetime pending request store."""

    settings = load_settings()
    return PendingRequestStore(ttl_seconds=settings.pending_request_ttl_seconds)


def get_execution_engine() -> ExecutionEngine:
    """Return the configured execution engine."""

    return ExecutionFactory(settings=load_settings()).create()
