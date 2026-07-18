"""Comprehensive tests for Aegis database persistence layer."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import (
    AuditEventModel,
    Base,
    PendingRequestModel,
)
from app.database.repositories import (
    AuditRepository,
    PendingRepository,
)
from app.database.services import (
    CleanupService,
    PersistenceService,
)
from app.rpc_parser import MCPRequestInfo, OperationType


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a isolated clean in-memory SQLite session for testing."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_local_maker = sessionmaker(bind=engine)
    db = session_local_maker()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ============================================================================
# 1. Repository CRUD Tests
# ============================================================================


def test_pending_repository_crud(db_session: Session) -> None:
    repo = PendingRepository(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)

    # 1. Add request
    req = PendingRequestModel(
        approval_id="app-1",
        nonce="nonce-1",
        payload_hash="hash-1",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="pod/mypod",
        raw_payload=b"{}",
        headers={"content-type": "application/json"},
        status="pending",
        expires_at=now + timedelta(seconds=300),
    )
    repo.add(req)
    db_session.commit()

    # 2. Get request
    stored = repo.get_by_nonce("nonce-1")
    assert stored is not None
    assert stored.approval_id == "app-1"
    assert stored.tool == "kubectl_delete"

    # 3. Get pending list
    pendings = repo.get_pending_approvals()
    assert len(pendings) == 1

    # 4. Get by approval_id
    stored2 = repo.get_by_approval_id("app-1")
    assert stored2 is not None

    # 5. Delete request
    deleted = repo.delete("nonce-1")
    assert deleted is True
    db_session.commit()

    assert repo.get_by_nonce("nonce-1") is None


def test_audit_repository_crud(db_session: Session) -> None:
    repo = AuditRepository(db_session)
    event = AuditEventModel(
        event_id="evt-1",
        event_type="REQUEST_INTERCEPTED",
        actor="system",
        recorded_at=datetime.now(UTC).replace(tzinfo=None),
        details={"info": "test"},
    )
    repo.add(event)
    db_session.commit()

    history = repo.get_audit_history()
    assert len(history) == 1
    assert history[0].event_type == "REQUEST_INTERCEPTED"
    assert history[0].details == {"info": "test"}


# ============================================================================
# 2. Service Layer & Security Tests
# ============================================================================


def test_persistence_service_header_redaction(db_session: Session) -> None:
    persistence = PersistenceService(db_session)
    headers = {
        "Host": "localhost",
        "Authorization": "Bearer mysecrettoken123",
        "X-API-Key": "apikeysecret",
        "Cookie": "session_id=abc",
    }
    redacted = persistence.redact_headers(headers)
    assert redacted["Host"] == "localhost"
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["X-API-Key"] == "[REDACTED]"
    assert redacted["Cookie"] == "[REDACTED]"


def test_intercept_request_creates_records_and_logs(db_session: Session) -> None:
    persistence = PersistenceService(db_session)
    req_info = MCPRequestInfo(
        jsonrpc="2.0",
        request_id=1,
        method="tools/call",
        tool_name="kubectl_delete",
        operation=OperationType.MUTATING,
    )
    headers = {"Authorization": "Bearer secret"}
    now = datetime.now(UTC)

    model = persistence.intercept_request(
        nonce="nonce-x",
        approval_id="approval-x",
        payload_hash="hash-x",
        body=b'{"params":{"arguments":{"namespace":"custom","resource_type":"pod","resource_name":"mypod"}}}',
        headers=headers,
        request_info=req_info,
        expires_at=now + timedelta(seconds=600),
    )
    db_session.commit()

    assert model.namespace == "custom"
    assert model.resource == "pod/mypod"
    assert model.headers["Authorization"] == "[REDACTED]"

    # Verify audit events were written
    audit_repo = AuditRepository(db_session)
    events = audit_repo.get_audit_history()
    event_types = [e.event_type for e in events]
    assert "REQUEST_INTERCEPTED" in event_types
    assert "REQUEST_STORED" in event_types


# ============================================================================
# 4. Expiration & Cleanup Service Tests
# ============================================================================


def test_cleanup_service_purges_and_archives(db_session: Session) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)

    # 1. Expired pending request (expires_at in past)
    req1 = PendingRequestModel(
        approval_id="app-exp",
        nonce="nonce-exp",
        payload_hash="hash-exp",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="",
        raw_payload=b"{}",
        headers={},
        status="pending",
        expires_at=now - timedelta(seconds=10),
    )
    db_session.add(req1)

    # 2. Completed request (should be archived)
    req2 = PendingRequestModel(
        approval_id="app-comp",
        nonce="nonce-comp",
        payload_hash="hash-comp",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="",
        raw_payload=b"{}",
        headers={},
        status="completed",
        expires_at=now + timedelta(seconds=300),
    )
    db_session.add(req2)
    db_session.commit()

    cleanup = CleanupService(db_session)
    result = cleanup.run_cleanup()

    assert result["deleted_expired"] == 1
    assert result["archived_completed"] == 1

    # Verify req1 is deleted
    stmt = select(PendingRequestModel).where(PendingRequestModel.nonce == "nonce-exp")
    assert db_session.execute(stmt).scalar_one_or_none() is None

    # Verify req2 status became archived
    db_session.refresh(req2)
    assert req2.status == "archived"


# ============================================================================
# 5. Database Restart & Recovery Tests
# ============================================================================


def test_database_restart_persistence() -> None:
    """Verifies that closing and reopening database preserves records (durable)."""
    # Create temporary database file
    temp_dir = tempfile.gettempdir()
    db_file_path = os.path.join(temp_dir, f"test_persist_{os.getpid()}.db")
    db_url = f"sqlite:///{db_file_path.replace(os.sep, '/')}"

    # 1. Open database and save a request
    engine1 = create_engine(db_url)
    Base.metadata.create_all(bind=engine1)
    session_maker_1 = sessionmaker(bind=engine1)

    db1 = session_maker_1()
    now = datetime.now(UTC).replace(tzinfo=None)
    req = PendingRequestModel(
        approval_id="app-durable",
        nonce="nonce-durable",
        payload_hash="hash-durable",
        tool="kubectl_delete",
        operation="mutating",
        namespace="default",
        resource="",
        raw_payload=b"{}",
        headers={},
        status="pending",
        expires_at=now + timedelta(seconds=300),
    )
    db1.add(req)
    db1.commit()
    db1.close()
    engine1.dispose()

    # 2. Re-open database with a new engine and retrieve
    engine2 = create_engine(db_url)
    session_maker_2 = sessionmaker(bind=engine2)
    db2 = session_maker_2()

    stmt = select(PendingRequestModel).where(
        PendingRequestModel.nonce == "nonce-durable"
    )
    retrieved = db2.execute(stmt).scalar_one_or_none()
    assert retrieved is not None
    assert retrieved.approval_id == "app-durable"

    db2.close()
    Base.metadata.drop_all(bind=engine2)
    engine2.dispose()

    # Delete temp file safely
    if os.path.exists(db_file_path):
        try:
            os.remove(db_file_path)
        except Exception:
            pass
