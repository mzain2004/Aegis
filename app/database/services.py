"""Service layer for business logic and database persistence integration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.database.models import (
    AuditEventModel,
    PendingRequestModel,
)
from app.database.repositories import (
    AuditRepository,
    PendingRepository,
)


class AuditService:
    """Service for registering immutable audit log events."""

    def __init__(self, db: Session) -> None:
        self.repo = AuditRepository(db)

    def log_event(
        self,
        event_type: str,
        details: dict[str, Any],
        actor: str | None = None,
        operator_id: int | None = None,
    ) -> AuditEventModel:
        event = AuditEventModel(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            actor=actor,
            operator_id=operator_id,
            recorded_at=datetime.now(UTC).replace(tzinfo=None),
            details=details,
        )
        self.repo.add(event)
        return event


class PersistenceService:
    """Service for redacting, storing, and loading intercepted requests."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.pending_repo = PendingRepository(db)
        self.audit_service = AuditService(db)

    def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Redact sensitive authorization and credential headers."""
        redacted = dict(headers)
        sensitive = {
            "authorization",
            "proxy-authorization",
            "x-api-key",
            "cookie",
            "set-cookie",
        }
        for key in redacted:
            if key.lower() in sensitive:
                redacted[key] = "[REDACTED]"
        return redacted

    def intercept_request(
        self,
        nonce: str,
        approval_id: str,
        payload_hash: str,
        body: bytes,
        headers: dict[str, str],
        request_info: Any,
        expires_at: datetime,
    ) -> PendingRequestModel:
        """Persist a newly suspended mutating request."""
        expires_at = (
            expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at
        )
        if not approval_id:
            approval_id = f"auto-{nonce}"
        # Extract metadata from JSON-RPC call info if present
        tool = request_info.tool_name or "unknown"
        operation = str(request_info.operation)

        # Parse namespace/resource if available
        namespace = "default"
        resource = ""
        try:
            import json

            payload_dict = json.loads(body.decode("utf-8"))
            params = payload_dict.get("params", {})
            arguments = params.get("arguments", {})
            if isinstance(arguments, dict):
                namespace = arguments.get("namespace", "default")
                resource_type = arguments.get("resource_type", "")
                resource_name = arguments.get("resource_name", "")
                if resource_type and resource_name:
                    resource = f"{resource_type}/{resource_name}"
                elif resource_type:
                    resource = resource_type
        except Exception:
            pass

        redacted_headers = self.redact_headers(headers)

        model = PendingRequestModel(
            approval_id=approval_id,
            nonce=nonce,
            payload_hash=payload_hash,
            tool=tool,
            operation=operation,
            namespace=namespace,
            resource=resource,
            raw_payload=body,
            headers=redacted_headers,
            status="pending",
            expires_at=expires_at,
        )

        self.pending_repo.add(model)

        self.audit_service.log_event(
            "REQUEST_INTERCEPTED",
            {
                "nonce": nonce,
                "approval_id": approval_id,
                "payload_hash": payload_hash,
                "tool": tool,
                "operation": operation,
            },
        )
        self.audit_service.log_event(
            "REQUEST_STORED",
            {
                "nonce": nonce,
                "approval_id": approval_id,
                "expires_at": expires_at.isoformat(),
            },
        )

        return model


class CleanupService:
    """Service for purging expired requests and archiving completed/failed requests."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.pending_repo = PendingRepository(db)
        self.audit_service = AuditService(db)

    def run_cleanup(self) -> dict[str, int]:
        """Delete expired pending requests and archive completed/failed requests."""
        now = datetime.now(UTC).replace(tzinfo=None)

        # 1. Clean up expired pending requests
        from sqlalchemy import select

        stmt_expired = select(PendingRequestModel).where(
            PendingRequestModel.expires_at <= now,
            PendingRequestModel.status == "pending",
        )
        expired_reqs = self.db.execute(stmt_expired).scalars().all()
        deleted_expired = len(expired_reqs)
        for req in expired_reqs:
            self.audit_service.log_event(
                "REQUEST_EXPIRED",
                {"nonce": req.nonce, "approval_id": req.approval_id},
            )
            self.audit_service.log_event(
                "REQUEST_CLEANED",
                {
                    "nonce": req.nonce,
                    "approval_id": req.approval_id,
                    "action": "deleted",
                },
            )
            self.db.delete(req)

        # 2. Archive completed or failed requests (mark status as archived)
        stmt_completed = select(PendingRequestModel).where(
            PendingRequestModel.status.in_(["completed", "failed"])
        )
        completed_reqs = self.db.execute(stmt_completed).scalars().all()
        archived_completed = len(completed_reqs)
        for req in completed_reqs:
            req.status = "archived"
            self.audit_service.log_event(
                "REQUEST_CLEANED",
                {
                    "nonce": req.nonce,
                    "approval_id": req.approval_id,
                    "action": "archived",
                },
            )

        # 3. Clean up old audit events according to configurable retention
        from datetime import timedelta

        from app.config import get_settings

        settings = get_settings()
        retention_days = settings.audit_retention_days
        cutoff_date = now - timedelta(days=retention_days)

        stmt_old_audits = select(AuditEventModel).where(
            AuditEventModel.recorded_at <= cutoff_date
        )
        old_audits = self.db.execute(stmt_old_audits).scalars().all()
        deleted_audits = len(old_audits)
        for audit in old_audits:
            self.db.delete(audit)

        # 4. Prune old/expired nonces if needed
        # (in our case, they are the pending_requests)

        self.db.flush()
        return {
            "deleted_expired": deleted_expired,
            "archived_completed": archived_completed,
            "deleted_audits": deleted_audits,
        }
