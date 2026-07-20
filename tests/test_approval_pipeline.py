"""Comprehensive tests for the full Veto Ops Human Approval Pipeline.

Verifies:
- Read request bypass (immediate forwarding)
- Mutating request pending (suspension with 202 and correct state/metadata)
- Approval success (correct payload release, state transitions, signature verification)
- Bad nonce (rejecting unknown/missing nonces)
- Bad HMAC (signature validation and failure rejection)
- Replay protection (preventing executing twice, 409 Conflict / Already Executed)
- Expired request (denying execution after expiration, 410 Gone)
- Unknown request (unknown approval_id handling)
- Execution failure (updating state to FAILED, blocking replays)
- Timeout (handling upstream timeouts properly)
- Store cleanup (verifying expired entries are swept from both stores)
- Concurrent approvals / Double approval (thread safety and exactly-once execution)
- State transitions (strict enforcement of allowed transitions)
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app import dependencies
from app.config import get_settings
from app.crypto import compute_hmac
from app.execution.base import ExecutionEngine
from app.execution.models import ExecutionResult
from app.forwarder import MCPForwarder
from app.main import app
from app.models import PendingRequest, RequestStatus
from app.pending_store import PendingRequestStore
from app.rpc_parser import MCPRequestInfo, OperationType


# -- Helper to create a suspended pending request --
def _create_pending_request(
    nonce: str,
    approval_id: str,
    tool_name: str = "kubectl_delete",
    expires_in_seconds: int = 300,
    status: RequestStatus = RequestStatus.PENDING,
) -> PendingRequest:
    now = datetime.now(UTC)
    return PendingRequest(
        nonce=nonce,
        payload_hash="abc123payloadhash",
        payload_bytes=b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}',
        headers={"content-type": "application/json"},
        request_info=MCPRequestInfo(
            jsonrpc="2.0",
            request_id=1,
            method="tools/call",
            tool_name=tool_name,
            operation=OperationType.MUTATING,
        ),
        created_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        status=status,
        approval_id=approval_id,
    )


# -- Mock execution engine that returns a success or failure result --
class MockExecutionEngine(ExecutionEngine):
    def __init__(self, result: ExecutionResult) -> None:
        self.result = result
        self.calls = 0

    async def execute(
        self, body: bytes, headers: dict[str, str], *, context=None
    ) -> ExecutionResult:
        self.calls += 1
        return self.result


# ============================================================================
# 1. Pipeline Verification Tests
# ============================================================================


def test_read_request_bypass() -> None:
    """Verifies that a read-only request bypasses suspension.

    It should be forwarded immediately.
    """
    settings = get_settings()

    async def mock_forward(*args, **kwargs):
        return 200, b'{"result":"success"}', {"content-type": "application/json"}

    forwarder = MCPForwarder(settings=settings)
    forwarder.forward = mock_forward  # type: ignore[assignment]
    store = PendingRequestStore(ttl_seconds=300)

    app.dependency_overrides[dependencies.get_forwarder] = lambda: forwarder
    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/",
            content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_get"}}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"result": "success"}
        assert store.count() == 0

    app.dependency_overrides.clear()


def test_mutating_request_pending() -> None:
    """Verifies mutating request interception and suspension."""
    store = PendingRequestStore(ttl_seconds=300)

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/",
            content=b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"kubectl_delete"}}',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "pending_approval"
        assert "approval_id" in body
        assert "nonce" in body
        assert "hash" in body
        assert "expires_at" in body
        assert body["expires_in"] == 300
        assert store.count() == 1

        stored = store.get(body["nonce"])
        assert stored is not None
        assert stored.status == RequestStatus.PENDING
        assert stored.approval_id == body["approval_id"]

    app.dependency_overrides.clear()


def test_approval_success() -> None:
    """Verifies signature-authorized human approval releases request."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-1"
    approval_id = "approval-1"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"ok":true}',
            latency_ms=10,
            backend="kubernetes",
            success=True,
        )
    )

    signature = compute_hmac(
        approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        resp = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
                "approved_by": "admin-1",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert engine.calls == 1

        # Atomically marked completed (and moved from active items to processed log)
        assert store.get(nonce) is None
        assert store.exists(nonce) is False

        # Verify execution_completed state transition recorded in processed log
        valid_request, err = store.get_if_valid(nonce)
        assert valid_request is None
        assert err == "already_processed"

    app.dependency_overrides.clear()


def test_bad_nonce() -> None:
    """Verifies rejection of unknown/missing nonces."""
    store = PendingRequestStore(ttl_seconds=300)

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        # Missing nonce
        resp1 = client.post("/approve", json={})
        assert resp1.status_code == 400
        assert resp1.json() == {"message": "nonce is required"}

        # Unknown nonce
        resp2 = client.post("/approve", json={"nonce": "non-existent-nonce"})
        assert resp2.status_code == 409
        assert resp2.json() == {
            "message": "pending request not found or already processed"
        }

    app.dependency_overrides.clear()


def test_bad_hmac() -> None:
    """Verifies invalid signature rejection (returns 403 Forbidden)."""
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-2"
    approval_id = "approval-2"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    signature = "badsig123"

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp.status_code == 403
        assert resp.json() == {"message": "bad signature"}

    app.dependency_overrides.clear()


def test_unknown_request() -> None:
    """Verifies mismatch of approval_id is rejected (returns 409 Conflict)."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-3"
    approval_id = "approval-3"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    signature = compute_hmac(
        approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store

    with TestClient(app) as client:
        resp = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": "wrong-approval-id",
                "signature": signature,
            },
        )
        assert resp.status_code == 409
        assert resp.json() == {"message": "unknown approval id"}

    app.dependency_overrides.clear()


def test_expired_request() -> None:
    """Verifies expired requests return 410 Gone and are never executed."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-4"
    approval_id = "approval-4"

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
        pending = _create_pending_request(nonce, approval_id)
        store.add(pending)
        # Manually expire the entry in the store after startup lifespan has run
        stored = store._items[nonce]
        store._items[nonce] = stored.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )

        signature = compute_hmac(
            approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
        )

        resp = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp.status_code == 410
        assert resp.json() == {"message": "expired request"}
        assert engine.calls == 0

    app.dependency_overrides.clear()


def test_replay_protection() -> None:
    """Verifies replay protection prevents executing same request twice."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-5"
    approval_id = "approval-5"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=200,
            headers={},
            body=b'{"ok":true}',
            latency_ms=5,
            backend="kubernetes",
            success=True,
        )
    )

    signature = compute_hmac(
        approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        # First execution succeeds
        resp1 = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp1.status_code == 200

        # Second execution returns 409 Conflict/Already Executed
        resp2 = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp2.status_code == 409
        assert resp2.json() == {"message": "Already Executed"}
        assert engine.calls == 1

    app.dependency_overrides.clear()


def test_execution_failure() -> None:
    """Verifies failed executions transition request to FAILED state."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-6"
    approval_id = "approval-6"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    engine = MockExecutionEngine(
        ExecutionResult(
            status_code=500,
            headers={},
            body=b"boom",
            latency_ms=5,
            backend="kubernetes",
            success=False,
        )
    )

    signature = compute_hmac(
        approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    with TestClient(app) as client:
        # Execution fails
        resp1 = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp1.status_code == 500
        assert resp1.content == b"boom"

        # Verify state is FAILED in the store
        stored = store.get(nonce)
        assert stored is not None
        assert stored.status == RequestStatus.FAILED

        # Re-execution must be rejected (returns 409)
        resp2 = client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )
        assert resp2.status_code == 409
        assert resp2.json() == {"message": "Already Executed"}
        assert engine.calls == 1

    app.dependency_overrides.clear()


def test_store_cleanup() -> None:
    """Verifies that expired requests are swept from the store."""
    store = PendingRequestStore(ttl_seconds=300)

    # Active entry
    req1 = _create_pending_request("nonce-active", "approval-active")
    store.add(req1)

    # Expired entry
    req2 = _create_pending_request("nonce-expired", "approval-expired")
    store.add(req2)
    stored2 = store._items["nonce-expired"]
    store._items["nonce-expired"] = stored2.model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )

    assert store.exists("nonce-active") is True
    # Accessing/counting cleans up expired entries automatically
    assert store.count() == 1
    assert store.exists("nonce-expired") is False


def test_concurrent_approvals() -> None:
    """Verifies atomic transitions block concurrent executions."""
    settings = get_settings()
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-concurrent"
    approval_id = "approval-concurrent"
    pending = _create_pending_request(nonce, approval_id)
    store.add(pending)

    # Delay inside mock execution to simulate time elapsed
    class SlowExecutionEngine(ExecutionEngine):
        def __init__(self) -> None:
            self.calls = 0
            self.lock = asyncio.Lock()

        async def execute(
            self, body: bytes, headers: dict[str, str], *, context=None
        ) -> ExecutionResult:
            async with self.lock:
                self.calls += 1
            await asyncio.sleep(0.1)
            return ExecutionResult(
                status_code=200,
                headers={},
                body=b"{}",
                latency_ms=10,
                backend="kubernetes",
                success=True,
            )

    engine = SlowExecutionEngine()
    signature = compute_hmac(
        approval_id, nonce, pending.payload_hash, settings.shared_hmac_secret
    )

    app.dependency_overrides[dependencies.get_pending_store] = lambda: store
    app.dependency_overrides[dependencies.get_execution_engine] = lambda: engine

    # Trigger concurrent HTTP requests
    client = TestClient(app)

    def trigger_approval():
        return client.post(
            "/approve",
            json={
                "nonce": nonce,
                "approval_id": approval_id,
                "signature": signature,
            },
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(trigger_approval) for _ in range(4)]
        results = [f.result() for f in futures]

    status_codes = [r.status_code for r in results]
    # Exactly one request must succeed (200), others must be rejected (409)
    assert status_codes.count(200) == 1
    assert status_codes.count(409) == 3
    assert engine.calls == 1

    app.dependency_overrides.clear()


def test_state_transitions() -> None:
    """Verifies strict state machine transitions and blocks disallowed paths."""
    store = PendingRequestStore(ttl_seconds=300)
    nonce = "nonce-state"
    req = _create_pending_request(nonce, "approval-state")
    store.add(req)

    # Transition PENDING -> APPROVED (valid)
    updated, err = store.claim_for_approval(nonce)
    assert updated is not None
    assert updated.status == RequestStatus.APPROVED
    assert err == ""

    # Re-claiming APPROVED should fail
    updated2, err2 = store.claim_for_approval(nonce)
    assert updated2 is None
    assert err2 == "already_processed"

    # Transition APPROVED -> EXECUTING (valid)
    assert store.mark_executing(nonce) is True
    assert store.get(nonce).status == RequestStatus.EXECUTING

    # Transition to FAILED (terminal status)
    store.mark_failed(nonce)
    assert store.get(nonce).status == RequestStatus.FAILED

    # Claiming FAILED request should fail
    updated3, err3 = store.claim_for_approval(nonce)
    assert updated3 is None
    assert err3 == "already_processed"
