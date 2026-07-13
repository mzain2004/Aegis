"""Cryptographic helpers for suspended MCP requests."""

from __future__ import annotations

import hashlib
import hmac
import uuid


def compute_sha256(data: bytes) -> str:
    """Return the lowercase SHA256 hex digest for raw bytes."""

    return hashlib.sha256(data).hexdigest()


def compute_hmac_sha256(secret: str, payload: bytes | str) -> str:
    """Return an HMAC-SHA256 signature for the supplied payload."""

    message = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_hmac_sha256(secret: str, payload: bytes | str, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature using constant-time comparison."""

    expected = compute_hmac_sha256(secret, payload)
    return hmac.compare_digest(expected, signature)


def generate_nonce() -> str:
    """Generate a UUID4 nonce for a pending request."""

    return str(uuid.uuid4())
