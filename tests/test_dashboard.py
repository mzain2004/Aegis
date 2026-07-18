"""Tests for the dashboard summary endpoint."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth_models import OperatorCreate, UserRole
from app.config import get_settings
from app.database import connection
from app.database.auth_services import OperatorService
from app.database.models import Base
from app.main import app
from app.monitoring.metrics import monitoring_service


@pytest.fixture
def auth_test_db() -> Generator[Session, None, None]:
    """Setup a clean test database specifically for authentication and RBAC tests."""
    import os
    import tempfile

    temp_dir = tempfile.gettempdir()
    db_file_path = os.path.join(temp_dir, f"test_auth_dashboard_{os.getpid()}.db")
    temp_db_url = f"sqlite:///{db_file_path.replace(os.sep, '/')}"

    engine = create_engine(temp_db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    # Store originals
    settings = get_settings()
    original_db_url = settings.database_url
    original_auth_enabled = settings.auth_enabled
    original_allow_anonymous_dev = settings.allow_anonymous_dev
    old_engine = connection.engine

    # Apply configuration overrides for these tests
    settings.database_url = temp_db_url
    settings.auth_enabled = True
    settings.allow_anonymous_dev = False
    connection.engine = engine

    session_maker = sessionmaker(bind=engine)
    connection.SessionLocal.configure(bind=engine)

    db = session_maker()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

        # Clean up database file
        if os.path.exists(db_file_path):
            try:
                os.remove(db_file_path)
            except Exception:
                pass

        # Restore configuration
        settings.database_url = original_db_url
        settings.auth_enabled = original_auth_enabled
        settings.allow_anonymous_dev = original_allow_anonymous_dev
        connection.engine = old_engine
        connection.SessionLocal.configure(bind=old_engine)


def test_dashboard_summary_returns_aggregated_metrics() -> None:
    """Verify that the /dashboard/summary endpoint correctly reports
    statistics and system health status."""
    # Reset local service metrics
    monitoring_service.reset()

    # Seed mock metrics for calculation testing
    monitoring_service.increment(
        "proxy_requests_total", 10.0, labels={"method": "POST", "route": "/"}
    )
    monitoring_service.increment(
        "authentication_failure", 2.0, labels={"reason": "invalid_key"}
    )

    with TestClient(app) as client:
        response = client.get("/dashboard/summary")
        assert response.status_code == 200
        data = response.json()

        # Verify returned summary statistics match seeded metrics
        assert "pending_requests" in data
        assert "completed_today" in data
        assert "failed_today" in data
        assert "execution_success_rate" in data
        assert "average_latency" in data
        assert data["authentication_failures"] == 2
        assert data["uptime"] >= 0.0
        assert data["system_health"] == "healthy"


def test_dashboard_summary_requires_authentication(auth_test_db: Session) -> None:
    """Verify that /dashboard/summary rejects unauthenticated requests."""
    with TestClient(app) as client:
        resp = client.get("/dashboard/summary")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Missing Authorization header" in resp.json()["detail"]


def test_dashboard_summary_allows_viewer_role(auth_test_db: Session) -> None:
    """Verify that a viewer-role operator (which holds VIEW_METRICS) can
    access /dashboard/summary."""
    op_service = OperatorService(auth_test_db)
    op_service.create_operator(
        OperatorCreate(
            username="viewer",
            display_name="Test Viewer",
            email="viewer@aegis.local",
            role=UserRole.VIEWER,
            active=True,
            api_key="viewer.api-key-1",
        )
    )

    with TestClient(app) as client:
        resp = client.get(
            "/dashboard/summary",
            headers={"Authorization": "Api-Key viewer.api-key-1"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert "pending_requests" in data
        assert "system_health" in data
