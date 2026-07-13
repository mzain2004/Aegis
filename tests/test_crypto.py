from __future__ import annotations

from app.crypto import (
    compute_hmac_sha256,
    compute_sha256,
    generate_nonce,
    verify_hmac_sha256,
)


def test_compute_sha256_is_deterministic() -> None:
    payload = b'{"jsonrpc":"2.0"}'

    first = compute_sha256(payload)
    second = compute_sha256(payload)

    assert first == second


def test_compute_sha256_differs_for_diff_bytes() -> None:
    first = compute_sha256(b"abc")
    second = compute_sha256(b"abd")

    assert first != second


def test_generate_nonce_produces_unique_values() -> None:
    values = {generate_nonce() for _ in range(100)}

    assert len(values) == 100


def test_compute_hmac_sha256_is_deterministic() -> None:
    signature = compute_hmac_sha256("shared-secret", b"nonce-123")

    assert signature == compute_hmac_sha256("shared-secret", b"nonce-123")


def test_verify_hmac_sha256_matches_expected_signature() -> None:
    signature = compute_hmac_sha256("shared-secret", b"nonce-123")

    assert verify_hmac_sha256("shared-secret", b"nonce-123", signature) is True
    assert verify_hmac_sha256("shared-secret", b"nonce-124", signature) is False
