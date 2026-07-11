"""Cryptographic helpers for suspended MCP requests."""

from __future__ import annotations

import hashlib
import uuid


def compute_sha256(data: bytes) -> str:
    """Return the lowercase SHA256 hex digest for raw bytes."""

    return hashlib.sha256(data).hexdigest()


def generate_nonce() -> str:
    """Generate a UUID4 nonce for a pending request."""

    return str(uuid.uuid4())