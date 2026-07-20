"""Dependency injection helpers for the FastAPI application."""

from __future__ import annotations

from collections.abc import Callable, Generator
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth_models import Permission
from app.config import Settings
from app.config import get_settings as load_settings
from app.database.connection import SessionLocal
from app.database.models import OperatorModel
from app.execution.base import ExecutionEngine
from app.execution.factory import ExecutionFactory
from app.forwarder import MCPForwarder
from app.logger import get_logger as build_logger
from app.pending_store import PendingRequestStore


def get_settings() -> Settings:
    """Return the cached application settings."""
    return load_settings()


def get_logger(name: str = "veto-ops") -> Any:
    """Return a structured logger for dependency injection."""
    return build_logger(name)


def get_forwarder(
    settings: Annotated[Settings, Depends(load_settings)],
) -> MCPForwarder:
    """Dependency that instantiates an `MCPForwarder` configured from settings."""
    return MCPForwarder(settings=settings)


@lru_cache(maxsize=1)
def get_pending_store() -> PendingRequestStore:
    """Return the application-lifetime pending request store."""
    settings = load_settings()
    return PendingRequestStore(ttl_seconds=settings.pending_request_ttl_seconds)


def get_execution_engine() -> ExecutionEngine:
    """Return the configured execution engine."""
    return ExecutionFactory(settings=load_settings()).create()


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional database session for requests."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_operator(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OperatorModel:
    """Authenticate the current operator using the Api-Key Authorization header."""
    if not settings.auth_enabled:
        # Authentication is disabled, return a mock admin operator
        return OperatorModel(
            id=0,
            username="anonymous_admin",
            display_name="Anonymous Administrator",
            email="admin@veto-ops.local",
            role="administrator",
            active=True,
        )

    auth_header = request.headers.get("Authorization")
    dev_operator = OperatorModel(
        id=0,
        username="anonymous_dev",
        display_name="Anonymous Developer",
        email="dev@veto-ops.local",
        role="administrator",
        active=True,
    )

    import structlog

    from app.audit.events import (
        OperatorAuthenticated,
        emit_audit_event,
    )
    from app.monitoring.metrics import monitoring_service
    from app.monitoring.tracing import correlation_id_ctx

    correlation_id = correlation_id_ctx.get()

    if not auth_header:
        if settings.allow_anonymous_dev:
            # Bind dev operator details
            structlog.contextvars.bind_contextvars(
                operator_id=0, operator_username="anonymous_dev"
            )
            return dev_operator
        monitoring_service.increment(
            "authentication_failure", labels={"reason": "missing_header"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Missing Authorization header",
        )

    # Expected format: "Api-Key xxxxx"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "api-key":
        if settings.allow_anonymous_dev:
            structlog.contextvars.bind_contextvars(
                operator_id=0, operator_username="anonymous_dev"
            )
            return dev_operator
        monitoring_service.increment(
            "authentication_failure", labels={"reason": "invalid_format"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid Authorization format. Use: Api-Key <key>",
        )

    api_key = parts[1].strip()
    import time

    from app.database.auth_services import AuthenticationService

    auth_service = AuthenticationService(db)
    auth_start = time.monotonic()
    operator = auth_service.authenticate_api_key(api_key)
    auth_latency_ms = (time.monotonic() - auth_start) * 1000.0
    monitoring_service.observe("authentication_latency", auth_latency_ms)

    if not operator:
        if settings.allow_anonymous_dev:
            structlog.contextvars.bind_contextvars(
                operator_id=0, operator_username="anonymous_dev"
            )
            return dev_operator
        monitoring_service.increment(
            "authentication_failure", labels={"reason": "invalid_key"}
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid API Key",
        )

    if not operator.active:
        monitoring_service.increment(
            "authentication_failure", labels={"reason": "disabled_account"}
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Operator account is disabled",
        )

    # Success: update metrics & context vars
    monitoring_service.increment(
        "authentication_success", labels={"username": operator.username}
    )
    structlog.contextvars.bind_contextvars(
        operator_id=operator.id, operator_username=operator.username
    )

    emit_audit_event(
        db,
        OperatorAuthenticated,
        correlation_id=correlation_id,
        operator_id=operator.id,
        actor=operator.username,
        status="authenticated",
    )

    return operator


def require_permission(
    permission: Permission,
) -> Callable[..., OperatorModel]:
    """Enforce that the current operator has the specified permission."""

    def dependency(
        operator: Annotated[OperatorModel, Depends(get_current_operator)],
        db: Annotated[Session, Depends(get_db)],
    ) -> OperatorModel:
        from app.audit.events import PermissionDenied, emit_audit_event
        from app.database.auth_services import AuthorizationService
        from app.monitoring.metrics import monitoring_service
        from app.monitoring.tracing import correlation_id_ctx

        if not AuthorizationService.has_permission(operator, permission):
            correlation_id = correlation_id_ctx.get()
            monitoring_service.increment(
                "permission_denied",
                labels={"username": operator.username, "permission": permission.value},
            )
            emit_audit_event(
                db,
                PermissionDenied,
                correlation_id=correlation_id,
                operator_id=operator.id,
                actor=operator.username,
                status="denied",
                details={"permission": permission.value},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Forbidden: Insufficient permissions. "
                    f"Required: {permission.value}"
                ),
            )
        return operator

    return dependency
