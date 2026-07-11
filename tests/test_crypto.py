from __future__ import annotations

from app.crypto import compute_sha256, generate_nonce


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