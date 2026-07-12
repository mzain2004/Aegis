"""MCP forwarder implementation for Phase 2.

This module implements a transparent, byte-preserving forwarder that sends
raw request bodies to an upstream Kubernetes MCP server and returns the
downstream response unchanged. Security, classification, and approval logic
are intentionally omitted and belong to later phases.
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings, get_settings
from app.logger import get_logger

LOGGER = get_logger(__name__)


class MCPForwarder:
    """Forward raw MCP requests to an upstream MCP server.

    Note: accepts an optional `httpx.AsyncClient` primarily for testing so
    that real network calls are not required when running unit tests.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    async def forward(
        self,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, bytes, dict[str, str]]:
        """Forward the given raw body and headers to the configured MCP server.

        Returns a tuple of (status_code, response_body, response_headers).
        """

        url = self.settings.k8s_mcp_server_url
        timeout = httpx.Timeout(self.settings.mcp_timeout_seconds)

        # Prepare client (use provided client for tests, otherwise create one)
        client_provided = self._client is not None
        client = self._client or httpx.AsyncClient()

        start = time.monotonic()
        try:
            # Send raw bytes; do not modify the payload in any way.
            resp = await client.post(
                url, content=body, headers=headers, timeout=timeout
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            LOGGER.info(
                "mcp_response_received",
                status=resp.status_code,
                latency_ms=latency_ms,
                destination=url,
            )

            # Convert headers to a plain dict
            resp_headers = {k: v for k, v in resp.headers.items()}
            return resp.status_code, resp.content, resp_headers

        except httpx.ReadTimeout as exc:
            LOGGER.warning("mcp_request_timeout", destination=url, error=str(exc))
            return 504, b"", {}
        except httpx.ConnectError as exc:
            LOGGER.warning("mcp_connection_error", destination=url, error=str(exc))
            return 503, b"", {}
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.error("mcp_forwarder_error", destination=url, error=str(exc))
            return 500, b"", {}
        finally:
            if not client_provided:
                await client.aclose()
