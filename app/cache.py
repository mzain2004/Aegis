"""Backward-compatible import for the in-memory pending request store."""

from __future__ import annotations

from app.pending_store import PendingRequestStore

__all__ = ["PendingRequestStore"]
