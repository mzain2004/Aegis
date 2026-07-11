"""Security helpers reserved for future zero-trust enforcement.

Phase 1 does not implement hashing, HMAC verification, or nonce generation.

TODO: add payload hashing, HMAC signature verification, and nonce issuance
when request suspension and approval flows are introduced.
"""

from __future__ import annotations

from typing import Any

from app.logger import get_logger

LOGGER = get_logger(__name__)


class SecurityManager:
    """Skeleton security service for future proxy protection features."""

    def hash_payload(self, payload: bytes | dict[str, Any]) -> str:
        """Hash a payload for later audit and deduplication logic.

        TODO: implement cryptographic hashing with domain-separated inputs.
        """

        LOGGER.debug("hash_payload_not_implemented")
        raise NotImplementedError("Payload hashing is reserved for a later phase.")

    def verify_hmac(self, payload: bytes, signature: str) -> bool:
        """Verify a payload signature.

        TODO: compare signed approval artifacts against the shared secret.
        """

        LOGGER.debug("verify_hmac_not_implemented")
        raise NotImplementedError("HMAC verification is reserved for a later phase.")

    def generate_nonce(self) -> str:
        """Generate a nonce for future approval and replay protection.

        TODO: bind generated nonces to the pending-request store and TTL policy.
        """

        LOGGER.debug("generate_nonce_not_implemented")
        raise NotImplementedError("Nonce generation is reserved for a later phase.")
