"""Background scheduler for operational database and audit cleanup."""

from __future__ import annotations

import asyncio

import structlog

from app.audit.events import CleanupCompleted, emit_audit_event
from app.database.connection import SessionLocal
from app.database.services import CleanupService

LOGGER = structlog.get_logger(__name__)


class CleanupScheduler:
    """Manages the background loop for running CleanupService periodically."""

    def __init__(self, interval_seconds: float = 3600.0) -> None:
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    def start(self) -> None:
        """Start the background cleanup loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        LOGGER.info("cleanup_scheduler_started", interval_seconds=self.interval_seconds)

    async def stop(self) -> None:
        """Stop the background cleanup loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        LOGGER.info("cleanup_scheduler_stopped")

    async def _loop(self) -> None:
        """Periodic loop executing database cleanup."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_seconds)
                self.run_scheduled_cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                LOGGER.error("cleanup_scheduler_loop_error", error=str(e))

    def run_scheduled_cleanup(self) -> dict[str, int]:
        """Open a db session and execute the CleanupService logic."""
        LOGGER.info("scheduled_cleanup_triggering")
        with SessionLocal() as db:
            service = CleanupService(db)
            results = service.run_cleanup()
            db.commit()

            # Emit CleanupCompleted audit event
            from app.monitoring.tracing import correlation_id_ctx

            correlation_id = correlation_id_ctx.get()
            emit_audit_event(
                db,
                CleanupCompleted,
                correlation_id=correlation_id,
                status="success",
                details=results,
            )

            LOGGER.info("scheduled_cleanup_completed", results=results)
            return results


# Global scheduler instance
cleanup_scheduler = CleanupScheduler()
