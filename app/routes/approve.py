"""Approval route handlers for releasing suspended requests."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.dependencies import get_execution_engine, get_pending_store
from app.logger import get_logger
from app.pending_store import PendingRequestStore
from app.execution.base import ExecutionEngine

LOGGER = get_logger(__name__)

router = APIRouter(prefix="/approve", tags=["approve"])

@router.post("/")
async def approve_entrypoint(
    request: Request,
    pending_store: PendingRequestStore = Depends(get_pending_store),
    execution_engine: ExecutionEngine = Depends(get_execution_engine),
) -> Response:
    """Release an approved pending request through the configured executor."""

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    nonce = payload.get("nonce") if isinstance(payload, dict) else None
    if not isinstance(nonce, str) or not nonce.strip():
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "nonce is required"},
        )

    pending_request = pending_store.get(nonce)
    if pending_request is None:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "pending request not found or already processed"},
        )

    result = await execution_engine.execute(
        pending_request.payload_bytes,
        pending_request.headers,
    )

    LOGGER.info(
        "execution_completed",
        request_id=pending_request.request_info.request_id,
        backend=result.backend,
        latency_ms=result.latency_ms,
        status=result.status_code,
        success=result.success,
    )

    if result.success:
        pending_store.remove(nonce)

    response = Response(content=result.body, status_code=result.status_code)
    for key, value in result.headers.items():
        response.headers[key] = value

    return response
