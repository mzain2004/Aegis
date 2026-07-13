"""Approval route handlers for releasing suspended requests."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.config import Settings
from app.dependencies import get_execution_engine, get_pending_store, get_settings
from app.execution.base import ExecutionEngine
from app.logger import get_logger
from app.pending_store import PendingRequestStore
from app.crypto import verify_hmac_sha256

LOGGER = get_logger(__name__)

router = APIRouter(prefix="/approve", tags=["approve"])


@router.post("/")
async def approve_entrypoint(
    request: Request,
    pending_store: Annotated[PendingRequestStore, Depends(get_pending_store)],
    execution_engine: Annotated[ExecutionEngine, Depends(get_execution_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
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

    signature = payload.get("signature") if isinstance(payload, dict) else None
    if isinstance(signature, str) and signature.strip():
        if not verify_hmac_sha256(settings.shared_hmac_secret, nonce, signature):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"message": "invalid signature"},
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
