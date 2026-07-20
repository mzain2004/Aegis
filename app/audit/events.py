"""Structured audit event definitions and emitter for Veto Ops."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.models import AuditEventModel

LOGGER = structlog.get_logger(__name__)

# Sensitive keys that must NEVER be included in audit events
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
    "signature",
    "hmac",
    "payload",
    "payload_bytes",
    "raw_payload",
    "body",
    "headers",
}


def sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively strip sensitive credentials, payloads, and tokens from details."""
    if not details:
        return {}

    sanitized: dict[str, Any] = {}
    for k, v in details.items():
        k_lower = k.lower()
        # Skip if key matches sensitive patterns
        if any(s_key in k_lower for s_key in SENSITIVE_KEYS):
            continue

        if isinstance(v, dict):
            sanitized[k] = sanitize_details(v)
        else:
            sanitized[k] = v

    return sanitized


class AuditEvent(BaseModel):
    """Base Pydantic schema for structured audit events."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str | None = None
    approval_id: str | None = None
    operator_id: int | None = None
    correlation_id: str | None = None
    latency: float | None = None
    status: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


# Specialized Event Types
class ProxyRequestReceived(AuditEvent):
    event_type: str = "ProxyRequestReceived"


class RequestClassified(AuditEvent):
    event_type: str = "RequestClassified"


class ApprovalCreated(AuditEvent):
    event_type: str = "ApprovalCreated"


class ApprovalValidated(AuditEvent):
    event_type: str = "ApprovalValidated"


class ApprovalRejected(AuditEvent):
    event_type: str = "ApprovalRejected"


class ExecutionStarted(AuditEvent):
    event_type: str = "ExecutionStarted"


class ExecutionFinished(AuditEvent):
    event_type: str = "ExecutionFinished"


class ExecutionFailed(AuditEvent):
    event_type: str = "ExecutionFailed"


class OperatorAuthenticated(AuditEvent):
    event_type: str = "OperatorAuthenticated"


class PermissionDenied(AuditEvent):
    event_type: str = "PermissionDenied"


class DatabaseMigrationApplied(AuditEvent):
    event_type: str = "DatabaseMigrationApplied"


class CleanupCompleted(AuditEvent):
    event_type: str = "CleanupCompleted"


def emit_audit_event(
    db: Session,
    event_class: type[AuditEvent],
    actor: str | None = None,
    request_id: str | None = None,
    approval_id: str | None = None,
    operator_id: int | None = None,
    correlation_id: str | None = None,
    latency: float | None = None,
    status: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Instantiate, sanitize, log, and persist a structured audit event
    to the database."""
    sanitized_details = sanitize_details(details)

    # Construct schema object
    event = event_class(  # type: ignore[call-arg]
        request_id=request_id,
        approval_id=approval_id,
        operator_id=operator_id,
        correlation_id=correlation_id,
        latency=latency,
        status=status,
        details=sanitized_details,
    )

    # Write to database (audit_events table)
    # Convert UTC datetime to naive for SQLite if necessary, matching existing patterns
    recorded_at = event.timestamp.replace(tzinfo=None)

    db_model = AuditEventModel(
        event_id=event.event_id,
        event_type=event.event_type,
        actor=actor or "system",
        operator_id=event.operator_id,
        recorded_at=recorded_at,
        details={
            "request_id": event.request_id,
            "approval_id": event.approval_id,
            "operator_id": event.operator_id,
            "correlation_id": event.correlation_id,
            "latency": event.latency,
            "status": event.status,
            **event.details,
        },
    )

    try:
        db.add(db_model)
        db.commit()
    except Exception as e:
        db.rollback()
        # Fallback to logger if db commit fails (e.g. during certain unit tests)
        LOGGER.error(
            "failed_to_persist_audit_event", error=str(e), event_type=event.event_type
        )

    # Log structured event via structlog
    # Standard logger outputs structured json
    log_args = {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "actor": actor or "system",
        "operator_id": event.operator_id,
        "correlation_id": event.correlation_id,
        "latency": event.latency,
        "status": event.status,
        **event.details,
    }

    LOGGER.info(
        f"Audit Event: {event.event_type}",
        **{k: v for k, v in log_args.items() if v is not None},
    )

    return event
