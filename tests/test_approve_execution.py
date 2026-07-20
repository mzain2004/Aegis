from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import dependencies
from app.crypto import compute_hmac_sha256
from app.execution.base import ExecutionEngine
from app.execution.models import ExecutionResult
from app.main import app
from app.models import PendingRequest
from app.pending_store import PendingRequestStore
from app.rpc_parser import MCPRequestInfo, OperationType


@dataclass
class MockExecutionEngine(ExecutionEngine):
    result: ExecutionResult
    calls: int = 0

    async def execute(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        context: object | None = None,
    ) -> ExecutionResult:
        self.calls += 1
        return self.result


def _pending_request(nonce: str = "nonce-1") -> PendingRequest:
    now = datetime.now(UTC)
    return PendingRequest(
        nonce=nonce,
        payload_hash="abc123",
        payload_bytes=b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}',
        headers={"content-type": "application/json"},
        request_info=MCPRequestInfo(
            jsonrpc="2.0",
            request_id=1,
            method="tools/call",
            tool_name="kubectl_delete",
            operation=OperationType.MUTATING,
        ),
        created_at=now,
        expires_at=now,
    )


def test_approved_request_executes_and_clears_store() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    pending = _pending_request()
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=200,
            headers={"content-type": "application/json", "x-upstream": "1"},
            body=b'{"ok":true}',
            latency_ms=12,
            backend="kubernetes",
            success=True,
        )
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        response = client.post("/approve", json={"nonce": pending.nonce})

        assert response.status_code == 200
        assert response.content == b'{"ok":true}'
        assert store.exists(pending.nonce) is False
        assert engine.calls == 1

    app.dependency_overrides.clear()


def test_duplicate_approval_is_rejected() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    pending = _pending_request("nonce-2")
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=200,
            headers={},
            body=b"{}",
            latency_ms=1,
            backend="kubernetes",
            success=True,
        )
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        first = client.post("/approve", json={"nonce": pending.nonce})
        second = client.post("/approve", json={"nonce": pending.nonce})

        assert first.status_code == 200
        assert second.status_code == 409
        assert engine.calls == 1

    app.dependency_overrides.clear()


def test_failed_execution_keeps_pending_request() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    pending = _pending_request("nonce-3")
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=500,
            headers={},
            body=b"",
            latency_ms=2,
            backend="kubernetes",
            success=False,
        )
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        response = client.post("/approve", json={"nonce": pending.nonce})

        assert response.status_code == 500
        assert store.exists(pending.nonce)
        assert engine.calls == 1

    app.dependency_overrides.clear()


def test_invalid_signature_is_rejected() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    pending = _pending_request("nonce-4")
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(status_code=200, headers={}, body=b"{}", latency_ms=1, backend="kubernetes", success=True)
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        response = client.post(
            "/approve",
            json={
                "nonce": pending.nonce,
                "signature": compute_hmac_sha256("development-shared-secret", b"wrong"),
            },
        )

        assert response.status_code == 403
        assert store.exists(pending.nonce)
        assert engine.calls == 0

    app.dependency_overrides.clear()
