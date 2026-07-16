"""Proxy route handlers for MCP forwarding and suspension."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.audit.events import (
    ApprovalCreated,
    ProxyRequestReceived,
    RequestClassified,
    emit_audit_event,
)
from app.crypto import compute_sha256, generate_nonce
from app.dependencies import get_db, get_forwarder, get_pending_store
from app.execution.models import execution_metrics
from app.forwarder import MCPForwarder
from app.logger import get_logger
from app.models import PendingRequest, RequestStatus
from app.monitoring.metrics import monitoring_service
from app.monitoring.tracing import correlation_id_ctx
from app.pending_store import PendingRequestStore
from app.rpc_parser import OperationType, parse_mcp_request

LOGGER = get_logger(__name__)

router = APIRouter(prefix="", tags=["proxy"])


@router.post("/")
async def proxy_entrypoint(
    request: Request,
    forwarder: Annotated[MCPForwarder, Depends(get_forwarder)],
    pending_store: Annotated[PendingRequestStore, Depends(get_pending_store)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Receive a raw MCP JSON-RPC request and forward it to the MCP server."""
    # Capture raw body
    body = await request.body()
    correlation_id = correlation_id_ctx.get()

    # Emit ProxyRequestReceived audit event
    emit_audit_event(
        db,
        ProxyRequestReceived,
        correlation_id=correlation_id,
        details={
            "method": request.method,
            "url": str(request.url),
            "size_bytes": len(body),
        },
    )

    import time

    parser_start = time.monotonic()
    request_info = parse_mcp_request(body)
    parser_latency_ms = (time.monotonic() - parser_start) * 1000.0
    monitoring_service.observe("parser_latency", parser_latency_ms)

    # Emit RequestClassified audit event
    emit_audit_event(
        db,
        RequestClassified,
        correlation_id=correlation_id,
        request_id=str(request_info.request_id or ""),
        details={
            "method": request_info.method,
            "tool": request_info.tool_name,
            "operation": request_info.operation.name,
        },
    )

    LOGGER.info(
        "MCP request classified",
        method=request_info.method,
        tool=request_info.tool_name,
        classification=request_info.operation.name,
    )

    incoming_headers = {k: v for k, v in request.headers.items()}

    if request_info.operation is OperationType.MUTATING:
        monitoring_service.increment("proxy_requests_mutating")
        monitoring_service.increment("proxy_requests_blocked")

        payload_hash = compute_sha256(body)
        nonce = generate_nonce()
        approval_id = generate_nonce()
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=pending_store.ttl_seconds)

        pending_request = PendingRequest(
            nonce=nonce,
            payload_hash=payload_hash,
            payload_bytes=body,
            headers=incoming_headers,
            request_info=request_info,
            created_at=now,
            expires_at=expires_at,
            status=RequestStatus.PENDING,
            approval_id=approval_id,
        )
        pending_store.add(pending_request)
        execution_metrics.record_pending()

        # Emit ApprovalCreated audit event
        emit_audit_event(
            db,
            ApprovalCreated,
            correlation_id=correlation_id,
            request_id=str(request_info.request_id or ""),
            approval_id=approval_id,
            details={
                "nonce": nonce,
                "expires_at": expires_at.isoformat(),
                "tool": request_info.tool_name,
            },
        )

        LOGGER.info(
            "Mutating request intercepted",
            nonce=nonce,
            approval_id=approval_id,
            payload_hash=payload_hash,
            expiration=expires_at.isoformat(),
            tool=request_info.tool_name,
            method=request_info.method,
        )

        return JSONResponse(
            status_code=202,
            content={
                "status": "pending_approval",
                "approval_id": approval_id,
                "nonce": nonce,
                "hash": payload_hash,
                "expires_at": expires_at.isoformat(),
                "expires_in": pending_store.ttl_seconds,
            },
        )

    if request_info.operation is OperationType.READ_ONLY:
        monitoring_service.increment("proxy_requests_read")
        LOGGER.info("Forwarding READ_ONLY request")

    # Log receipt (without payloads or auth headers)
    LOGGER.info(
        "mcp_proxy_request_received",
        method=request.method,
        size_bytes=len(body),
        destination=forwarder.settings.k8s_mcp_server_url,
    )

    monitoring_service.increment("proxy_requests_forwarded")
    status_code, resp_body, resp_headers = await forwarder.forward(
        body, incoming_headers
    )

    # Build response; pass through headers but avoid forbidden hop-by-hop
    response = Response(content=resp_body, status_code=status_code)
    for k, v in resp_headers.items():
        # Skip hop-by-hop headers that are managed by the ASGI server
        if k.lower() in {
            "transfer-encoding",
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "upgrade",
        }:
            continue
        response.headers[k] = v

    return response
