"""Comprehensive tests for Veto Ops Authentication and Role-Based Access Control (RBAC)."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth_models import OperatorCreate, UserRole
from app.config import get_settings
from app.database import connection
from app.database.auth_services import (
    OperatorService,
    hash_api_key,
    verify_api_key,
)
from app.database.bootstrap import bootstrap_database
from app.database.models import Base, OperatorModel, PendingRequestModel
from app.database.repositories import AuditRepository, OperatorRepository
from app.main import app


@pytest.fixture
def auth_test_db() -> Generator[Session, None, None]:
    """Setup a clean test database specifically for authentication and RBAC tests."""
    import os
    import tempfile

    temp_dir = tempfile.gettempdir()
    db_file_path = os.path.join(temp_dir, f"test_auth_{os.getpid()}.db")
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


@pytest.fixture
def populated_operators(auth_test_db: Session) -> dict[str, str]:
    """Create operators with different roles and return API keys."""
    op_service = OperatorService(auth_test_db)

    # Viewer
    op_service.create_operator(
        OperatorCreate(
            username="viewer",
            display_name="Test Viewer",
            email="viewer@veto-ops.local",
            role=UserRole.VIEWER,
            active=True,
            api_key="viewer.api-key-1",
        )
    )

    # Approver
    op_service.create_operator(
        OperatorCreate(
            username="approver",
            display_name="Test Approver",
            email="approver@veto-ops.local",
            role=UserRole.APPROVER,
            active=True,
            api_key="approver.api-key-2",
        )
    )

    # Administrator
    op_service.create_operator(
        OperatorCreate(
            username="admin",
            display_name="Test Admin",
            email="admin@veto-ops.local",
            role=UserRole.ADMINISTRATOR,
            active=True,
            api_key="admin.api-key-3",
        )
    )

    # Disabled operator
    op_service.create_operator(
        OperatorCreate(
            username="disabled_admin",
            display_name="Disabled Admin",
            email="disabled@veto-ops.local",
            role=UserRole.ADMINISTRATOR,
            active=False,
            api_key="disabled.api-key-4",
        )
    )

    return {
        "viewer": "viewer.api-key-1",
        "approver": "approver.api-key-2",
        "admin": "admin.api-key-3",
        "disabled": "disabled.api-key-4",
    }


# ============================================================================
# 1. Hashing and Verification Tests
# ============================================================================


def test_api_key_hashing() -> None:
    plaintext = "super-secret-api-key"
    hashed = hash_api_key(plaintext)
    assert hashed != plaintext
    assert verify_api_key(hashed, plaintext) is True
    assert verify_api_key(hashed, "wrong-key") is False


# ============================================================================
# 2. Operator Repository & Service CRUD Tests
# ============================================================================


def test_operator_crud(auth_test_db: Session) -> None:
    repo = OperatorRepository(auth_test_db)

    # Test Create
    model = OperatorModel(
        username="john",
        display_name="John Doe",
        email="john@veto-ops.local",
        api_key_hash=hash_api_key("john.key"),
        role="viewer",
        active=True,
    )
    repo.add(model)
    auth_test_db.commit()

    # Test Read
    retrieved = repo.get_by_username("john")
    assert retrieved is not None
    assert retrieved.display_name == "John Doe"
    assert retrieved.role == "viewer"

    retrieved_by_id = repo.get_by_id(retrieved.id)
    assert retrieved_by_id is not None
    assert retrieved_by_id.username == "john"

    # Test Update (via service)
    service = OperatorService(auth_test_db)
    from app.auth_models import OperatorUpdate

    updated = service.update_operator(
        retrieved.id,
        OperatorUpdate(display_name="John Updater", role=UserRole.APPROVER),
    )
    assert updated is not None
    assert updated.display_name == "John Updater"
    assert updated.role == "approver"

    # Test Delete
    success = service.delete_operator(retrieved.id)
    assert success is True
    assert repo.get_by_username("john") is None


# ============================================================================
# 3. Authentication & Middleware Tests
# ============================================================================


def test_authentication_missing_header(auth_test_db: Session) -> None:
    with TestClient(app) as client:
        # Request should fail with 401 Unauthorized
        resp = client.get("/approve/pending")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Missing Authorization header" in resp.json()["detail"]


def test_authentication_invalid_format(auth_test_db: Session) -> None:
    with TestClient(app) as client:
        # Request has header, but not prefixed with Api-Key
        resp = client.get(
            "/approve/pending", headers={"Authorization": "Bearer badtoken"}
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid Authorization format" in resp.json()["detail"]


def test_authentication_wrong_key(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    with TestClient(app) as client:
        resp = client.get(
            "/approve/pending", headers={"Authorization": "Api-Key wrong-key"}
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED
        assert "Invalid API Key" in resp.json()["detail"]


def test_authentication_disabled_user(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    with TestClient(app) as client:
        disabled_key = populated_operators["disabled"]
        resp = client.get(
            "/approve/pending", headers={"Authorization": f"Api-Key {disabled_key}"}
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "Operator account is disabled" in resp.json()["detail"]


def test_authentication_success_updates_last_login(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    repo = OperatorRepository(auth_test_db)
    viewer = repo.get_by_username("viewer")
    assert viewer is not None
    assert viewer.last_login is None

    with TestClient(app) as client:
        viewer_key = populated_operators["viewer"]
        resp = client.get(
            "/approve/pending", headers={"Authorization": f"Api-Key {viewer_key}"}
        )
        assert resp.status_code == status.HTTP_200_OK

        # Verify last login timestamp was updated in DB
        auth_test_db.refresh(viewer)
        assert viewer.last_login is not None


# ============================================================================
# 4. Role-Based Access Control (RBAC) Permissions Tests
# ============================================================================


def test_rbac_viewer_permissions(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    viewer_key = populated_operators["viewer"]
    headers = {"Authorization": f"Api-Key {viewer_key}"}

    with TestClient(app) as client:
        # Viewer CAN view pending
        resp = client.get("/approve/pending", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Viewer CAN view history
        resp = client.get("/approve/history", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Viewer CAN view audit
        resp = client.get("/approve/audit", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Viewer CANNOT approve
        resp = client.post("/approve/", json={"nonce": "nonce-x"}, headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Viewer CANNOT cleanup
        resp = client.post("/approve/cleanup", headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Viewer CANNOT manage users
        resp = client.get("/approve/operators", headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_rbac_approver_permissions(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    approver_key = populated_operators["approver"]
    headers = {"Authorization": f"Api-Key {approver_key}"}

    # Store a request to approve
    now = datetime.now(UTC).replace(tzinfo=None)
    req = PendingRequestModel(
        approval_id="app-auth",
        nonce="nonce-auth",
        payload_hash="hash-auth",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="",
        raw_payload=b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"kubectl_delete"}}',
        headers={},
        status="pending",
        expires_at=now + timedelta(seconds=300),
    )
    auth_test_db.add(req)
    auth_test_db.commit()

    with TestClient(app) as client:
        # Approver CAN view logs
        resp = client.get("/approve/pending", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Approver CAN approve (returns 200/500/etc., not 403 Forbidden)
        resp = client.post("/approve/", json={"nonce": "nonce-auth"}, headers=headers)
        assert resp.status_code != status.HTTP_403_FORBIDDEN

        # Approver CANNOT cleanup
        resp = client.post("/approve/cleanup", headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN

        # Approver CANNOT manage users
        resp = client.get("/approve/operators", headers=headers)
        assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_rbac_admin_permissions(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    admin_key = populated_operators["admin"]
    headers = {"Authorization": f"Api-Key {admin_key}"}

    with TestClient(app) as client:
        # Admin CAN view pending
        resp = client.get("/approve/pending", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Admin CAN trigger cleanup
        resp = client.post("/approve/cleanup", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Admin CAN list operators
        resp = client.get("/approve/operators", headers=headers)
        assert resp.status_code == status.HTTP_200_OK

        # Admin CAN create operator
        new_op = {
            "username": "newop",
            "display_name": "New Operator",
            "email": "new@veto-ops.local",
            "role": "approver",
            "active": True,
            "api_key": "newop.key123",
        }
        resp = client.post("/approve/operators", json=new_op, headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["username"] == "newop"

        # Admin CAN delete operator
        repo = OperatorRepository(auth_test_db)
        new_op_model = repo.get_by_username("newop")
        assert new_op_model is not None

        resp = client.delete(f"/approve/operators/{new_op_model.id}", headers=headers)
        assert resp.status_code == status.HTTP_200_OK


# ============================================================================
# 5. Audit Logging Operator Tracking Tests
# ============================================================================


def test_audit_logs_operator_id(
    auth_test_db: Session, populated_operators: dict[str, str]
) -> None:
    admin_key = populated_operators["admin"]
    headers = {"Authorization": f"Api-Key {admin_key}"}

    # Store a request
    now = datetime.now(UTC).replace(tzinfo=None)
    req = PendingRequestModel(
        approval_id="app-audit-test",
        nonce="nonce-audit-test",
        payload_hash="hash-audit-test",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="",
        raw_payload=b'{"jsonrpc":"2.0","method":"tools/call","params":{"name":"kubectl_delete"}}',
        headers={},
        status="pending",
        expires_at=now + timedelta(seconds=300),
    )
    auth_test_db.add(req)
    auth_test_db.commit()

    with TestClient(app) as client:
        # Perform approval
        resp = client.post(
            "/approve/", json={"nonce": "nonce-audit-test"}, headers=headers
        )
        assert resp.status_code != status.HTTP_403_FORBIDDEN

        # Query audit history
        audit_repo = AuditRepository(auth_test_db)
        history = audit_repo.get_audit_history()

        # Find the APPROVAL_GRANTED event
        grant_event = next(
            (e for e in history if e.event_type == "APPROVAL_GRANTED"), None
        )
        assert grant_event is not None

        # Verify the actor and operator_id match our admin operator
        repo = OperatorRepository(auth_test_db)
        admin_op = repo.get_by_username("admin")
        assert admin_op is not None

        assert grant_event.actor == "admin"
        assert grant_event.operator_id == admin_op.id


# ============================================================================
# 6. Database Bootstrapping Tests
# ============================================================================


def test_bootstrap_creates_default_admin(auth_test_db: Session) -> None:
    # Ensure operators table is currently empty
    repo = OperatorRepository(auth_test_db)
    assert len(repo.list_operators()) == 0

    # Run bootstrap
    bootstrap_database(auth_test_db)

    # Verify default admin operator was created
    settings = get_settings()
    admin = repo.get_by_username(settings.default_admin_username)
    assert admin is not None
    assert admin.role == "administrator"
    assert admin.active is True
    assert verify_api_key(admin.api_key_hash, settings.default_admin_apikey) is True
