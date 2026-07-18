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


def compute_hmac(
    approval_id: str,
    nonce: str,
    payload_hash: str,
    secret: str,
) -> str:
    """Compute HMAC-SHA256 over ``approval_id:nonce:payload_hash``.

    Parameters
    ----------
    approval_id:
        Unique identifier for the approval request.
    nonce:
        Single-use nonce bound to the request.
    payload_hash:
        SHA-256 hex digest of the serialised payload.
    secret:
        Shared HMAC secret (from ``get_settings().shared_hmac_secret``).

    Returns
    -------
    str
        Lowercase hex digest of the HMAC-SHA256 signature.
    """

    message = f"{approval_id}:{nonce}:{payload_hash}"
    return hmac.new(
        key=secret.encode(),
        msg=message.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_hmac(
    approval_id: str,
    nonce: str,
    payload_hash: str,
    secret: str,
    signature: str,
) -> bool:
    """Verify an HMAC-SHA256 signature using constant-time comparison.

    Parameters
    ----------
    approval_id:
        Unique identifier for the approval request.
    nonce:
        Single-use nonce bound to the request.
    payload_hash:
        SHA-256 hex digest of the serialised payload.
    secret:
        Shared HMAC secret (from ``get_settings().shared_hmac_secret``).
    signature:
        The hex-encoded HMAC signature to verify.

    Returns
    -------
    bool
        ``True`` when *signature* matches the expected HMAC, ``False``
        otherwise.  Never raises on an invalid signature.
    """

    expected = compute_hmac(approval_id, nonce, payload_hash, secret)
    return hmac.compare_digest(expected, signature)
