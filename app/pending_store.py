"""Thread-safe database-backed store for suspended MCP requests."""

from __future__ import annotations

import functools
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.config import get_settings
from app.database.connection import SessionLocal
from app.database.models import PendingRequestModel
from app.database.repositories import PendingRepository
from app.database.services import (
    AuditService,
    CleanupService,
    PersistenceService,
)
from app.models import PendingRequest, RequestStatus
from app.rpc_parser import parse_mcp_request


def time_store_op(func):  # type: ignore
    @functools.wraps(func)
    def wrapper(*args, **kwargs):  # type: ignore
        start = time.monotonic()
        try:
            return func(*args, **kwargs)
        finally:
            duration_ms = (time.monotonic() - start) * 1000.0
            from app.monitoring.metrics import monitoring_service

            monitoring_service.observe("store_latency", duration_ms)

    return wrapper


def _strip_tz(dt: datetime) -> datetime:
    """Strip timezone info from datetime for database compatibility."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _to_pydantic(model: PendingRequestModel) -> PendingRequest:
    """Helper to convert SQLAlchemy model to Pydantic model."""
    return PendingRequest(
        nonce=model.nonce,
        payload_hash=model.payload_hash,
        payload_bytes=model.raw_payload,
        headers=model.headers,
        request_info=parse_mcp_request(model.raw_payload),
        created_at=model.created_at,
        expires_at=model.expires_at,
        status=RequestStatus(model.status),
        approval_id=model.approval_id,
    )


class DbItemsWrapper:
    """Mock dict interface over the database for backward compatibility in tests."""

    def __init__(self, store: PendingRequestStore) -> None:
        self.store = store

    def __getitem__(self, nonce: str) -> PendingRequest:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is None:
                raise KeyError(nonce)
            return _to_pydantic(model)

    def __setitem__(self, nonce: str, value: PendingRequest) -> None:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is not None:
                model.status = str(value.status)
                model.approval_id = value.approval_id
                model.payload_hash = value.payload_hash
                model.raw_payload = value.payload_bytes
                model.headers = value.headers
                model.created_at = _strip_tz(value.created_at)
                model.expires_at = _strip_tz(value.expires_at)
            else:
                model = PendingRequestModel(
                    nonce=nonce,
                    approval_id=value.approval_id or f"auto-{nonce}",
                    payload_hash=value.payload_hash,
                    tool=value.request_info.tool_name or "unknown",
                    operation=str(value.request_info.operation),
                    namespace="default",
                    resource="",
                    raw_payload=value.payload_bytes,
                    headers=value.headers,
                    status=str(value.status),
                    created_at=_strip_tz(value.created_at),
                    expires_at=_strip_tz(value.expires_at),
                )
                repo.add(model)
            db.commit()

    def __contains__(self, nonce: str) -> bool:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            return model is not None

    def items(self) -> list[tuple[str, PendingRequest]]:
        with SessionLocal() as db:
            from sqlalchemy import select

            stmt = select(PendingRequestModel)
            models = db.execute(stmt).scalars().all()
            return [(m.nonce, _to_pydantic(m)) for m in models]


class PendingRequestStore:
    """Store pending requests in database for later approval phases."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        settings = get_settings()
        self._ttl_seconds = (
            ttl_seconds
            if ttl_seconds is not None
            else settings.pending_request_ttl_seconds
        )

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def _items(self) -> DbItemsWrapper:
        """Provide a dictionary-like wrapper for test compatibility."""
        return DbItemsWrapper(self)

    @time_store_op
    def add(self, request: PendingRequest) -> None:
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self._ttl_seconds)

        with SessionLocal() as db:
            service = PersistenceService(db)
            service.intercept_request(
                nonce=request.nonce,
                approval_id=request.approval_id,
                payload_hash=request.payload_hash,
                body=request.payload_bytes,
                headers=request.headers,
                request_info=request.request_info,
                expires_at=expires_at,
            )
            db.commit()

    @time_store_op
    def get(self, nonce: str) -> PendingRequest | None:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model:
                # Expire check
                now = datetime.now(UTC).replace(tzinfo=None)
                if _strip_tz(model.expires_at) <= now and model.status == "pending":
                    model.status = "expired"
                    audit = AuditService(db)
                    audit.log_event(
                        "REQUEST_EXPIRED",
                        {"nonce": nonce, "approval_id": model.approval_id},
                    )
                    db.commit()
                    return None

                # Return request only if status is not completed/archived
                if model.status in ("completed", "archived"):
                    return None

                return _to_pydantic(model)
            return None

    @time_store_op
    def remove(self, nonce: str) -> None:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            repo.delete(nonce)
            db.commit()

    @time_store_op
    def cleanup_expired(self) -> None:
        with SessionLocal() as db:
            service = CleanupService(db)
            service.run_cleanup()
            db.commit()

    @time_store_op
    def count(self) -> int:
        self.cleanup_expired()
        with SessionLocal() as db:
            repo = PendingRepository(db)
            pending = repo.get_pending_approvals()
            return len(pending)

    @time_store_op
    def exists(self, nonce: str) -> bool:
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            # True as long as request is active and not completed/archived
            return model is not None and model.status not in ("completed", "archived")

    # -- New State Machine and Replay Protection Methods --

    @time_store_op
    def get_if_valid(self, nonce: str) -> tuple[PendingRequest | None, str]:
        """Check if request exists, is not expired, and is not already processed."""
        with SessionLocal() as db:
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is None:
                return None, "not_found"

            if model.status in ("completed", "failed", "archived"):
                return None, "already_processed"

            now = datetime.now(UTC).replace(tzinfo=None)
            if _strip_tz(model.expires_at) <= now:
                model.status = "expired"
                audit = AuditService(db)
                audit.log_event(
                    "REQUEST_EXPIRED",
                    {"nonce": nonce, "approval_id": model.approval_id},
                )
                db.commit()
                return None, "expired"

            return _to_pydantic(model), ""

    @time_store_op
    def claim_for_approval(
        self,
        nonce: str,
        operator_username: str = "system",
        operator_id: int | None = None,
        signature_verified: bool = False,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[PendingRequest | None, str]:
        """Atomically transition request from PENDING to APPROVED status."""
        now = datetime.now(UTC).replace(tzinfo=None)
        with SessionLocal() as db:
            # 1. Optimistic atomic update
            stmt = (
                update(PendingRequestModel)
                .where(
                    PendingRequestModel.nonce == nonce,
                    PendingRequestModel.status == "pending",
                )
                .values(
                    status="approved",
                    approved_at=now,
                    approved_by=operator_username,
                )
            )
            res = db.execute(stmt)
            if res.rowcount == 0:  # type: ignore[attr-defined]
                # Let's see why it failed: expired, already processed, or not found?
                repo = PendingRepository(db)
                model = repo.get_by_nonce(nonce)
                if model is None:
                    return None, "not_found"
                if model.status in ("completed", "failed", "archived"):
                    return None, "already_processed"
                if _strip_tz(model.expires_at) <= now:
                    model.status = "expired"
                    audit = AuditService(db)
                    audit.log_event(
                        "REQUEST_EXPIRED",
                        {"nonce": nonce, "approval_id": model.approval_id},
                    )
                    db.commit()
                    return None, "expired"
                return None, "already_processed"

            # 2. Reload and log event
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is not None:
                # Write approval record
                from app.database.models import ApprovalRecordModel
                from app.database.repositories import ApprovalRepository

                approval_repo = ApprovalRepository(db)
                rec = ApprovalRecordModel(
                    approval_id=model.approval_id,
                    operator=operator_username,
                    operator_id=operator_id,
                    signature_verified=signature_verified,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                approval_repo.add(rec)

                audit = AuditService(db)
                audit.log_event(
                    "APPROVAL_GRANTED",
                    {
                        "nonce": nonce,
                        "approval_id": model.approval_id,
                        "operator": operator_username,
                        "signature_verified": signature_verified,
                    },
                    actor=operator_username,
                    operator_id=operator_id,
                )
                db.commit()
                return _to_pydantic(model), ""

            db.commit()
            return None, "not_found"

    @time_store_op
    def mark_executing(self, nonce: str, operator_id: int | None = None) -> bool:
        """Transition request from APPROVED to EXECUTING status."""
        with SessionLocal() as db:
            stmt = (
                update(PendingRequestModel)
                .where(
                    PendingRequestModel.nonce == nonce,
                    PendingRequestModel.status == "approved",
                )
                .values(status="executing")
            )
            res = db.execute(stmt)
            if res.rowcount == 0:  # type: ignore[attr-defined]
                return False

            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is not None:
                audit = AuditService(db)
                audit.log_event(
                    "EXECUTION_STARTED",
                    {"nonce": nonce, "approval_id": model.approval_id},
                    operator_id=operator_id,
                )
            db.commit()
            return True

    @time_store_op
    def mark_completed(self, nonce: str, operator_id: int | None = None) -> None:
        """Transition request to COMPLETED."""
        now = datetime.now(UTC).replace(tzinfo=None)
        with SessionLocal() as db:
            stmt = (
                update(PendingRequestModel)
                .where(
                    PendingRequestModel.nonce == nonce,
                    PendingRequestModel.status == "executing",
                )
                .values(status="completed", completed_at=now)
            )
            res = db.execute(stmt)
            if res.rowcount > 0:  # type: ignore[attr-defined]
                repo = PendingRepository(db)
                model = repo.get_by_nonce(nonce)
                if model is not None:
                    audit = AuditService(db)
                    audit.log_event(
                        "EXECUTION_COMPLETED",
                        {"nonce": nonce, "approval_id": model.approval_id},
                        operator_id=operator_id,
                    )
            db.commit()

    @time_store_op
    def mark_failed(self, nonce: str, operator_id: int | None = None) -> None:
        """Transition request to FAILED."""
        now = datetime.now(UTC).replace(tzinfo=None)
        with SessionLocal() as db:
            # Atomic failed transition
            repo = PendingRepository(db)
            model = repo.get_by_nonce(nonce)
            if model is not None:
                model.status = "failed"
                model.failed_at = now
                model.retry_count += 1

                audit = AuditService(db)
                audit.log_event(
                    "EXECUTION_FAILED",
                    {"nonce": nonce, "approval_id": model.approval_id},
                    operator_id=operator_id,
                )
            db.commit()
