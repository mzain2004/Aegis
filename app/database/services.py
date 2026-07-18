"""Service layer for business logic and database persistence integration."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.crypto import verify_hmac
from app.database.models import (
    ApprovalRecordModel,
    AuditEventModel,
    ExecutionRecordModel,
    PendingRequestModel,
)
from app.database.repositories import (
    ApprovalRepository,
    AuditRepository,
    ExecutionRepository,
    PendingRepository,
)
from app.execution.base import ExecutionEngine
from app.execution.models import ExecutionContext, ExecutionStatus, execution_metrics


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


class ApprovalService:
    """Service for handling human approval signatures and state transitions."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.pending_repo = PendingRepository(db)
        self.approval_repo = ApprovalRepository(db)
        self.audit_service = AuditService(db)

    def verify_and_claim(
        self,
        nonce: str,
        approval_id: str | None,
        signature: str | None,
        operator: str,
        hmac_secret: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        operator_id: int | None = None,
    ) -> tuple[PendingRequestModel | None, str]:
        """Verify the signature and atomically claim the request for approval.

        Returns (model, error_reason).
        """
        # Load request
        req = self.pending_repo.get_by_nonce(nonce)
        if not req:
            return None, "not_found"

        # Check if already processed
        if req.status in ("completed", "failed"):
            return None, "already_processed"

        # Check if expired
        now = datetime.now(UTC).replace(tzinfo=None)
        if req.expires_at <= now:
            req.status = "expired"
            self.db.flush()
            self.audit_service.log_event(
                "REQUEST_EXPIRED",
                {"nonce": nonce, "approval_id": req.approval_id},
                operator_id=operator_id,
            )
            return None, "expired"

        # Log approval request received
        self.audit_service.log_event(
            "APPROVAL_REQUESTED",
            {"nonce": nonce, "approval_id": req.approval_id, "operator": operator},
            actor=operator,
            operator_id=operator_id,
        )

        # Mismatch of approval_id if provided
        if approval_id is not None and approval_id != req.approval_id:
            self.audit_service.log_event(
                "APPROVAL_REJECTED",
                {
                    "nonce": nonce,
                    "approval_id": req.approval_id,
                    "reason": "approval_id_mismatch",
                },
                actor=operator,
                operator_id=operator_id,
            )
            return None, "id_mismatch"

        # Validate signature
        sig_verified = False
        if signature is not None:
            verify_id = approval_id or req.approval_id
            if not verify_hmac(
                verify_id,
                nonce,
                req.payload_hash,
                hmac_secret,
                signature,
            ):
                self.audit_service.log_event(
                    "APPROVAL_REJECTED",
                    {
                        "nonce": nonce,
                        "approval_id": req.approval_id,
                        "reason": "bad_signature",
                    },
                    actor=operator,
                    operator_id=operator_id,
                )
                return None, "bad_signature"
            sig_verified = True

        # Transition state: pending -> approved
        from sqlalchemy import update

        stmt = (
            update(PendingRequestModel)
            .where(
                PendingRequestModel.nonce == nonce,
                PendingRequestModel.status == "pending",
            )
            .values(
                status="approved",
                approved_at=datetime.now(UTC).replace(tzinfo=None),
                approved_by=operator,
            )
        )
        res = self.db.execute(stmt)
        if res.rowcount == 0:  # type: ignore[attr-defined]
            return None, "already_processed"

        # Reload model
        req = self.pending_repo.get_by_nonce(nonce)
        if not req:
            return None, "not_found"
        self.db.flush()

        # Write approval record
        rec = ApprovalRecordModel(
            approval_id=req.approval_id,
            operator=operator,
            operator_id=operator_id,
            signature_verified=sig_verified,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self.approval_repo.add(rec)

        self.audit_service.log_event(
            "APPROVAL_GRANTED",
            {
                "nonce": nonce,
                "approval_id": req.approval_id,
                "operator": operator,
                "signature_verified": sig_verified,
            },
            actor=operator,
            operator_id=operator_id,
        )

        return req, ""


class ExecutionService:
    """Service for running approved payloads and persisting execution runs."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.pending_repo = PendingRepository(db)
        self.exec_repo = ExecutionRepository(db)
        self.audit_service = AuditService(db)

    async def execute_approved(
        self,
        req: PendingRequestModel,
        execution_engine: ExecutionEngine,
        operator: str,
        operator_id: int | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        """Transition request to executing, run the executor, and save results."""
        nonce = req.nonce

        # 1. State transition to executing
        req.status = "executing"
        self.db.flush()

        self.audit_service.log_event(
            "EXECUTION_STARTED",
            {
                "nonce": nonce,
                "approval_id": req.approval_id,
                "backend": req.execution_backend or "kubernetes",
            },
            actor=operator,
            operator_id=operator_id,
        )

        # 2. Prepare ExecutionContext
        context = ExecutionContext(
            request_id=str(req.id),
            approval_id=req.approval_id,
            operator=operator,
            request_fingerprint=req.payload_hash,
            execution_target=req.tool,
            status=ExecutionStatus.RUNNING,
        )

        execution_id = context.execution_id
        backend_name = req.execution_backend or "kubernetes"

        # Record start of run in database
        exec_record = ExecutionRecordModel(
            execution_id=execution_id,
            approval_id=req.approval_id,
            status="running",
            backend=backend_name,
            started_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.exec_repo.add(exec_record)
        self.db.flush()

        # 3. Dispatch execution
        exec_start = datetime.now(UTC).replace(tzinfo=None)
        try:
            import inspect

            sig = inspect.signature(execution_engine.execute)
            if "context" in sig.parameters:
                result = await execution_engine.execute(
                    req.raw_payload,
                    req.headers,
                    context=context,
                )
            else:
                result = await execution_engine.execute(
                    req.raw_payload,
                    req.headers,
                )

            end_time = datetime.now(UTC).replace(tzinfo=None)
            duration_ms = int((end_time - exec_start).total_seconds() * 1000)

            # Update request status and metrics based on outcome
            if result.success:
                req.status = "completed"
                req.completed_at = end_time

                exec_record.status = "completed"
                exec_record.completed_at = end_time
                exec_record.duration_ms = duration_ms
                exec_record.http_status = result.status_code

                self.db.flush()

                self.audit_service.log_event(
                    "EXECUTION_COMPLETED",
                    {
                        "nonce": nonce,
                        "approval_id": req.approval_id,
                        "execution_id": execution_id,
                        "duration_ms": duration_ms,
                        "http_status": result.status_code,
                    },
                    actor=operator,
                    operator_id=operator_id,
                )
            else:
                req.status = "failed"
                req.failed_at = end_time
                req.retry_count += 1

                exec_record.status = "failed"
                exec_record.completed_at = end_time
                exec_record.duration_ms = duration_ms
                exec_record.http_status = result.status_code
                exec_record.error_type = result.error_type
                exec_record.retryable = result.retryable

                self.db.flush()

                self.audit_service.log_event(
                    "EXECUTION_FAILED",
                    {
                        "nonce": nonce,
                        "approval_id": req.approval_id,
                        "execution_id": execution_id,
                        "error_type": result.error_type,
                        "retryable": result.retryable,
                    },
                    actor=operator,
                    operator_id=operator_id,
                )

            return result.status_code, result.body, result.headers

        except Exception as exc:
            end_time = datetime.now(UTC).replace(tzinfo=None)
            duration_ms = int((end_time - exec_start).total_seconds() * 1000)

            req.status = "failed"
            req.failed_at = end_time
            req.retry_count += 1

            exec_record.status = "failed"
            exec_record.completed_at = end_time
            exec_record.duration_ms = duration_ms
            exec_record.http_status = 500
            exec_record.error_type = "unexpected_error"
            exec_record.retryable = False

            self.db.flush()

            self.audit_service.log_event(
                "EXECUTION_FAILED",
                {
                    "nonce": nonce,
                    "approval_id": req.approval_id,
                    "execution_id": execution_id,
                    "error_type": "unexpected_error",
                    "error_detail": str(exc),
                },
                actor=operator,
                operator_id=operator_id,
            )

            # Record standard execution metrics failure
            execution_metrics.record_execution(
                success=False,
                latency_ms=duration_ms,
            )

            raise


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
