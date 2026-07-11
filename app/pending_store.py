"""Thread-safe in-memory store for suspended MCP requests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock

from app.config import get_settings
from app.models import PendingRequest


class PendingRequestStore:
    """Store pending requests in memory for later approval phases."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        settings = get_settings()
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.pending_request_ttl_seconds
        self._items: dict[str, PendingRequest] = {}
        self._lock = Lock()

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def add(self, request: PendingRequest) -> None:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self._ttl_seconds)
        stored_request = request.model_copy(
            update={"created_at": now, "expires_at": expires_at}
        )

        with self._lock:
            self._cleanup_expired_locked(now)
            self._items[stored_request.nonce] = stored_request

    def get(self, nonce: str) -> PendingRequest | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._cleanup_expired_locked(now)
            return self._items.get(nonce)

    def remove(self, nonce: str) -> None:
        with self._lock:
            self._items.pop(nonce, None)

    def cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._cleanup_expired_locked(now)

    def count(self) -> int:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._cleanup_expired_locked(now)
            return len(self._items)

    def exists(self, nonce: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._cleanup_expired_locked(now)
            return nonce in self._items

    def _cleanup_expired_locked(self, now: datetime) -> None:
        expired_nonces = [
            nonce for nonce, request in self._items.items() if request.expires_at <= now
        ]
        for nonce in expired_nonces:
            self._items.pop(nonce, None)