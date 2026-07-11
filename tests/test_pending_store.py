from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from app.models import PendingRequest
from app.pending_store import PendingRequestStore
from app.rpc_parser import MCPRequestInfo, OperationType


def _pending_request(nonce: str, expires_in_seconds: int = 300) -> PendingRequest:
    now = datetime.now(timezone.utc)
    return PendingRequest(
        nonce=nonce,
        payload_hash="abc123",
        payload_bytes=b'{"jsonrpc":"2.0"}',
        headers={"content-type": "application/json"},
        request_info=MCPRequestInfo(
            jsonrpc="2.0",
            request_id=1,
            method="tools/call",
            tool_name="kubectl_delete",
            operation=OperationType.MUTATING,
        ),
        created_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
    )


def test_pending_store_add_get_remove() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    request = _pending_request("nonce-1")

    store.add(request)

    stored = store.get("nonce-1")
    assert stored is not None
    assert stored.nonce == "nonce-1"

    store.remove("nonce-1")
    assert store.get("nonce-1") is None


def test_pending_store_cleanup_removes_expired_entries() -> None:
    store = PendingRequestStore(ttl_seconds=300)
    request = _pending_request("nonce-2")

    store.add(request)

    stored = store.get("nonce-2")
    assert stored is not None
    store._items["nonce-2"] = stored.model_copy(
        update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}
    )

    store.cleanup_expired()
    assert store.count() == 0


def test_pending_store_basic_thread_safety() -> None:
    store = PendingRequestStore(ttl_seconds=300)

    def add_item(index: int) -> None:
        store.add(_pending_request(f"nonce-{index}"))

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add_item, range(32)))

    assert store.count() == 32
    assert store.exists("nonce-0")