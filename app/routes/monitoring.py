"""Monitoring and health check routes for Veto Ops."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from datetime import time as datetime_time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.repositories import (
    ExecutionRepository,
    OperatorRepository,
    PendingRepository,
)
from app.dependencies import get_db
from app.monitoring.metrics import monitoring_service

router = APIRouter(tags=["monitoring"])


async def run_with_timeout(coro: Any, timeout: float) -> Any:
    """Run a coroutine with a maximum timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        raise TimeoutError("Check timed out") from None


def check_db_health(db: Session) -> bool:
    """Validate database connectivity."""
    try:
        db.execute(text("SELECT 1")).scalar()
        return True
    except Exception:
        return False


def check_pending_store(db: Session) -> bool:
    """Validate that the pending requests repository/store is operational."""
    try:
        repo = PendingRepository(db)
        repo.get_pending_approvals()
        return True
    except Exception:
        return False


def check_execution_health() -> bool:
    """Validate the execution engine configuration."""
    try:
        settings = get_settings()
        from app.execution.factory import ExecutionFactory

        # Verify factory can resolve backend
        factory = ExecutionFactory(settings)
        factory.create()
        return True
    except Exception:
        return False


def check_auth_subsystem(db: Session) -> bool:
    """Validate operator database table integrity and seeding status."""
    try:
        repo = OperatorRepository(db)
        # Operators list query
        repo.list_operators()
        return True
    except Exception:
        return False


@router.get("/health")
async def health_endpoint(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Liveness probe representing basic application reachability."""
    db_ok = check_db_health(db)
    status_str = "healthy" if db_ok else "unhealthy"
    return {"status": status_str}


@router.get("/live")
async def live_endpoint() -> dict[str, Any]:
    """Fast liveness check for container orchestration."""
    return {"status": "alive", "timestamp": datetime.now(UTC).isoformat()}


@router.get("/ready")
async def ready_endpoint(db: Annotated[Session, Depends(get_db)]) -> Response:
    """Readiness check validating all external dependencies and sub-systems."""
    settings = get_settings()
    timeout = float(settings.health_check_timeout)

    checks: dict[str, Any] = {}

    async def run_checks() -> None:
        # Execute checks
        checks["database"] = check_db_health(db)
        checks["pending_store"] = check_pending_store(db)
        checks["execution_framework"] = check_execution_health()
        checks["configuration"] = True  # Settings loaded successfully
        checks["authentication_subsystem"] = check_auth_subsystem(db)
        checks["metrics_subsystem"] = True  # Metrics module loaded

    try:
        await asyncio.wait_for(run_checks(), timeout=timeout)
        all_ok = all(checks.values())
        status_code = (
            status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        )
    except Exception as e:
        all_ok = False
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        checks["error"] = str(e)

    res_body = {
        "status": "ready" if all_ok else "not_ready",
        "timestamp": datetime.now(UTC).isoformat(),
        "checks": checks,
    }

    # Track metrics if configured
    if settings.metrics_enabled:
        monitoring_service.gauge("active_pending_requests", len(checks))

    return JSONResponse(content=res_body, status_code=status_code)


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    """Expose Prometheus metrics in text format."""
    settings = get_settings()
    if not settings.prometheus_enabled:
        return Response(
            content="Prometheus metrics are disabled",
            media_type="text/plain",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    # Refresh uptime metric in MonitoringService
    monitoring_service.snapshot()

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/dashboard/summary")
async def dashboard_summary(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Retrieve operational statistics and health summary for dashboard
    visualization."""

    # 1. Pending requests
    pending_repo = PendingRepository(db)
    pending_count = len(pending_repo.get_pending_approvals())

    # 2. Executions today
    exec_repo = ExecutionRepository(db)
    all_history = exec_repo.get_execution_history()

    # Filter for today
    today_start = datetime.combine(datetime.now(UTC).date(), datetime_time.min)
    today_history = [r for r in all_history if r.started_at >= today_start]

    completed_today = sum(1 for r in today_history if r.status == "completed")
    failed_today = sum(1 for r in today_history if r.status == "failed")

    # 3. Success rate
    total_today = completed_today + failed_today
    if total_today > 0:
        success_rate = (completed_today / total_today) * 100.0
    else:
        # Fallback to overall history
        total_history = sum(
            1 for r in all_history if r.status in ("completed", "failed")
        )
        completed_history = sum(1 for r in all_history if r.status == "completed")
        if total_history > 0:
            success_rate = (completed_history / total_history) * 100.0
        else:
            success_rate = 100.0

    # 4. Average Latency
    durations = [r.duration_ms for r in all_history if r.duration_ms is not None]
    avg_latency = sum(durations) / len(durations) if durations else 0.0

    # 5. Uptime & Failures from Monitoring snapshot
    snap = monitoring_service.snapshot()
    uptime = snap.get("uptime_seconds", 0.0)
    auth_failures = snap.get("authentication_failure", 0.0)

    # 6. Active users
    op_repo = OperatorRepository(db)
    active_users = sum(1 for o in op_repo.list_operators() if o.active)

    # 7. System health status
    sys_healthy = check_db_health(db) and check_pending_store(db)

    return {
        "pending_requests": pending_count,
        "completed_today": completed_today,
        "failed_today": failed_today,
        "execution_success_rate": round(success_rate, 2),
        "average_latency": round(avg_latency, 2),
        "authentication_failures": int(auth_failures),
        "uptime": round(uptime, 2),
        "active_users": active_users,
        "system_health": "healthy" if sys_healthy else "unhealthy",
    }
