"""Proxy route handlers for MCP forwarding and suspension."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.crypto import compute_sha256, generate_nonce
from app.dependencies import get_forwarder, get_pending_store
from app.logger import get_logger
from app.models import PendingRequest
from app.pending_store import PendingRequestStore
from app.rpc_parser import OperationType
from app.rpc_parser import parse_mcp_request
from app.forwarder import MCPForwarder

LOGGER = get_logger(__name__)

router = APIRouter(prefix="", tags=["proxy"])

@router.post("/")
async def proxy_entrypoint(
    request: Request,
    forwarder: MCPForwarder = Depends(get_forwarder),
    pending_store: PendingRequestStore = Depends(get_pending_store),
) -> Response:
    """Receive a raw MCP JSON-RPC request and forward it to the MCP server.

    This endpoint preserves the exact request bytes and headers and returns
    the upstream response unchanged. Classification and approval are not
    performed in Phase 2.
    """

    # Capture raw body
    body = await request.body()

    request_info = parse_mcp_request(body)
    LOGGER.info(
        "MCP request classified",
        method=request_info.method,
        tool=request_info.tool_name,
        classification=request_info.operation.name,
    )

    incoming_headers = {k: v for k, v in request.headers.items()}

    if request_info.operation is OperationType.MUTATING:
        payload_hash = compute_sha256(body)
        nonce = generate_nonce()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=pending_store.ttl_seconds)
        pending_request = PendingRequest(
            nonce=nonce,
            payload_hash=payload_hash,
            payload_bytes=body,
            headers=incoming_headers,
            request_info=request_info,
            created_at=now,
            expires_at=expires_at,
        )
        pending_store.add(pending_request)

        LOGGER.info(
            "Mutating request intercepted",
            nonce=nonce,
            payload_hash=payload_hash,
            expiration=expires_at.isoformat(),
            tool=request_info.tool_name,
            method=request_info.method,
        )

        return JSONResponse(
            status_code=202,
            content={
                "status": "pending_approval",
                "nonce": nonce,
                "expires_in": pending_store.ttl_seconds,
            },
        )

    if request_info.operation is OperationType.READ_ONLY:
        LOGGER.info("Forwarding READ_ONLY request")

    # Capture headers as a plain dict; avoid logging sensitive headers
    # Log receipt (without payloads or auth headers)
    LOGGER.info(
        "mcp_proxy_request_received",
        method=request.method,
        size_bytes=len(body),
        destination=forwarder.settings.k8s_mcp_server_url,
    )

    status_code, resp_body, resp_headers = await forwarder.forward(body, incoming_headers)

    # Build response; pass through headers but avoid forbidden hop-by-hop
    response = Response(content=resp_body, status_code=status_code)
    for k, v in resp_headers.items():
        # Skip hop-by-hop headers that are managed by the ASGI server
        if k.lower() in {"transfer-encoding", "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "upgrade"}:
            continue
        response.headers[k] = v

    return response
