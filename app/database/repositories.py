"""Repository layer for database operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    ApprovalRecordModel,
    AuditEventModel,
    ExecutionRecordModel,
    OperatorModel,
    PendingRequestModel,
)


class OperatorRepository:
    """Repository for managing OperatorModel instances."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, model: OperatorModel) -> None:
        self.db.add(model)
        self.db.flush()

    def get_by_id(self, operator_id: int) -> OperatorModel | None:
        stmt = select(OperatorModel).where(OperatorModel.id == operator_id)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_username(self, username: str) -> OperatorModel | None:
        stmt = select(OperatorModel).where(OperatorModel.username == username)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_api_key_hash(self, api_key_hash: str) -> OperatorModel | None:
        stmt = select(OperatorModel).where(OperatorModel.api_key_hash == api_key_hash)
        return self.db.execute(stmt).scalar_one_or_none()

    def list_operators(self) -> list[OperatorModel]:
        stmt = select(OperatorModel).order_by(OperatorModel.id.asc())
        return list(self.db.execute(stmt).scalars().all())

    def delete(self, operator_id: int) -> bool:
        model = self.get_by_id(operator_id)
        if model:
            self.db.delete(model)
            self.db.flush()
            return True
        return False


class PendingRepository:
    """Repository for managing PendingRequestModel instances."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, model: PendingRequestModel) -> None:
        self.db.add(model)
        self.db.flush()

    def get_by_nonce(self, nonce: str) -> PendingRequestModel | None:
        stmt = select(PendingRequestModel).where(PendingRequestModel.nonce == nonce)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_approval_id(self, approval_id: str) -> PendingRequestModel | None:
        stmt = select(PendingRequestModel).where(
            PendingRequestModel.approval_id == approval_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_pending_approvals(self) -> list[PendingRequestModel]:
        stmt = select(PendingRequestModel).where(
            PendingRequestModel.status == "pending"
        )
        return list(self.db.execute(stmt).scalars().all())

    def delete(self, nonce: str) -> bool:
        model = self.get_by_nonce(nonce)
        if model:
            self.db.delete(model)
            self.db.flush()
            return True
        return False

    def cleanup_expired(self) -> int:
        """Delete expired pending requests and return the count of deleted items."""
        now = datetime.now(UTC)
        stmt = select(PendingRequestModel).where(
            PendingRequestModel.expires_at <= now,
            PendingRequestModel.status == "pending",
        )
        expired = self.db.execute(stmt).scalars().all()
        count = len(expired)
        for item in expired:
            self.db.delete(item)
        self.db.flush()
        return count


class ApprovalRepository:
    """Repository for managing ApprovalRecordModel instances."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, model: ApprovalRecordModel) -> None:
        self.db.add(model)
        self.db.flush()

    def get_by_approval_id(self, approval_id: str) -> ApprovalRecordModel | None:
        stmt = select(ApprovalRecordModel).where(
            ApprovalRecordModel.approval_id == approval_id
        )
        return self.db.execute(stmt).scalar_one_or_none()


class ExecutionRepository:
    """Repository for managing ExecutionRecordModel instances."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, model: ExecutionRecordModel) -> None:
        self.db.add(model)
        self.db.flush()

    def get_by_execution_id(self, execution_id: str) -> ExecutionRecordModel | None:
        stmt = select(ExecutionRecordModel).where(
            ExecutionRecordModel.execution_id == execution_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_execution_history(self) -> list[ExecutionRecordModel]:
        stmt = select(ExecutionRecordModel).order_by(
            ExecutionRecordModel.started_at.desc()
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_failed_executions(self) -> list[ExecutionRecordModel]:
        stmt = select(ExecutionRecordModel).where(
            ExecutionRecordModel.status == "failed"
        )
        return list(self.db.execute(stmt).scalars().all())


class AuditRepository:
    """Repository for managing AuditEventModel instances."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, model: AuditEventModel) -> None:
        self.db.add(model)
        self.db.flush()

    def get_audit_history(self) -> list[AuditEventModel]:
        stmt = select(AuditEventModel).order_by(AuditEventModel.recorded_at.desc())
        return list(self.db.execute(stmt).scalars().all())
