"""Tests for database cleanup and background scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.database.connection import SessionLocal
from app.database.models import AuditEventModel
from app.database.services import CleanupService
from app.monitoring.cleanup_scheduler import cleanup_scheduler


def test_cleanup_service_retention_purges_old_audits() -> None:
    """Verify that CleanupService.run_cleanup purges audit logs older
    than audit_retention_days."""
    with SessionLocal() as db:
        # Create an audit event from 40 days ago
        old_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=40)
        old_event = AuditEventModel(
            event_id="old-event-123",
            event_type="TEST_OLD_EVENT",
            actor="system",
            recorded_at=old_time,
            details={},
        )
        # Create an audit event from today
        recent_event = AuditEventModel(
            event_id="recent-event-123",
            event_type="TEST_RECENT_EVENT",
            actor="system",
            recorded_at=datetime.now(UTC).replace(tzinfo=None),
            details={},
        )
        db.add(old_event)
        db.add(recent_event)
        db.commit()

        # Run cleanup
        service = CleanupService(db)
        results = service.run_cleanup()
        db.commit()

        # Verify old audit event is deleted, recent one is preserved
        stmt = select(AuditEventModel).where(
            AuditEventModel.event_id == "old-event-123"
        )
        old_res = db.execute(stmt).scalar_one_or_none()
        assert old_res is None

        stmt_recent = select(AuditEventModel).where(
            AuditEventModel.event_id == "recent-event-123"
        )
        recent_res = db.execute(stmt_recent).scalar_one_or_none()
        assert recent_res is not None

        assert results["deleted_audits"] >= 1


def test_scheduler_manual_execution() -> None:
    """Verify that manual execution of the scheduler runs correctly."""
    results = cleanup_scheduler.run_scheduled_cleanup()
    assert "deleted_expired" in results
    assert "archived_completed" in results
    assert "deleted_audits" in results
