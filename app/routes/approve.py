"""Approval route handlers for releasing suspended requests.

Integrates the complete human approval workflow including signature validation,
state machine enforcement, and execution dispatching.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth_models import OperatorCreate, OperatorSchema, Permission
from app.config import Settings
from app.crypto import verify_hmac
from app.database.models import OperatorModel
from app.dependencies import (
    get_db,
    get_execution_engine,
    get_pending_store,
    get_settings,
    require_permission,
)
from app.execution.base import ExecutionEngine
from app.execution.models import ExecutionContext, ExecutionStatus, execution_metrics
from app.logger import get_logger
from app.pending_store import PendingRequestStore

LOGGER = get_logger(__name__)

router = APIRouter(prefix="/approve", tags=["approve"])


@router.post("/")
async def approve_entrypoint(
    request: Request,
    pending_store: Annotated[PendingRequestStore, Depends(get_pending_store)],
    execution_engine: Annotated[ExecutionEngine, Depends(get_execution_engine)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.APPROVE_REQUEST))
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """Release an approved pending request through the configured executor."""
    start_time = time.monotonic()

    from app.audit.events import (
        ApprovalRejected,
        ApprovalValidated,
        ExecutionFailed,
        ExecutionFinished,
        ExecutionStarted,
        emit_audit_event,
    )
    from app.monitoring.metrics import monitoring_service
    from app.monitoring.tracing import correlation_id_ctx

    correlation_id = correlation_id_ctx.get()

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    nonce = payload.get("nonce") if isinstance(payload, dict) else None
    if not isinstance(nonce, str) or not nonce.strip():
        execution_metrics.record_rejected()
        monitoring_service.increment("approvals_rejected")
        emit_audit_event(
            db,
            ApprovalRejected,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            status="rejected",
            details={"reason": "nonce_missing"},
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "nonce is required"},
        )

    # 1. Validation and Replay Protection Check
    pending_request, error_reason = pending_store.get_if_valid(nonce)
    if error_reason == "expired":
        execution_metrics.record_expired()
        monitoring_service.increment("approvals_expired")
        emit_audit_event(
            db,
            ApprovalRejected,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            status="expired",
            details={"nonce": nonce, "reason": "expired"},
        )
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={"message": "expired request"},
        )
    elif error_reason == "already_processed":
        monitoring_service.increment("approvals_replayed")
        emit_audit_event(
            db,
            ApprovalRejected,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            status="replayed",
            details={"nonce": nonce, "reason": "already_processed"},
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "Already Executed"},
        )
    elif error_reason == "not_found" or pending_request is None:
        monitoring_service.increment("approvals_rejected")
        emit_audit_event(
            db,
            ApprovalRejected,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            status="not_found",
            details={"nonce": nonce, "reason": "not_found"},
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "pending request not found or already processed"},
        )

    # Bind approval_id to contextvars
    structlog.contextvars.bind_contextvars(approval_id=pending_request.approval_id)

    # 2. Match approval_id if provided
    req_approval_id = payload.get("approval_id")
    if req_approval_id is not None and req_approval_id != pending_request.approval_id:
        execution_metrics.record_rejected()
        monitoring_service.increment("approvals_rejected")
        emit_audit_event(
            db,
            ApprovalRejected,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            approval_id=pending_request.approval_id,
            status="rejected",
            details={"reason": "approval_id_mismatch"},
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "unknown approval id"},
        )

    # 3. Verify HMAC signature if provided
    signature = payload.get("signature")
    signature_verified = False
    if signature is not None:
        verify_id = req_approval_id or pending_request.approval_id
        secret = settings.shared_hmac_secret
        if not verify_hmac(
            verify_id,
            nonce,
            pending_request.payload_hash,
            secret,
            signature,
        ):
            execution_metrics.record_rejected()
            monitoring_service.increment("approvals_rejected")
            emit_audit_event(
                db,
                ApprovalRejected,
                correlation_id=correlation_id,
                operator_id=current_operator.id,
                actor=current_operator.username,
                approval_id=verify_id,
                status="rejected",
                details={"reason": "bad_signature"},
            )
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"message": "bad signature"},
            )
        signature_verified = True

    # Emit ApprovalValidated audit event
    emit_audit_event(
        db,
        ApprovalValidated,
        correlation_id=correlation_id,
        operator_id=current_operator.id,
        actor=current_operator.username,
        approval_id=pending_request.approval_id,
        status="validated",
        details={"signature_verified": signature_verified},
    )

    # Get client details
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # 4. Atomic claim (transition PENDING -> APPROVED)
    claimed_request, claim_err = pending_store.claim_for_approval(
        nonce,
        operator_username=current_operator.username,
        operator_id=current_operator.id,
        signature_verified=signature_verified,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if claim_err == "expired":
        execution_metrics.record_expired()
        monitoring_service.increment("approvals_expired")
        return JSONResponse(
            status_code=status.HTTP_410_GONE,
            content={"message": "expired request"},
        )
    elif claim_err == "already_processed":
        monitoring_service.increment("approvals_replayed")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "Already Executed"},
        )
    elif claim_err == "not_found" or claimed_request is None:
        monitoring_service.increment("approvals_rejected")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "pending request not found or already processed"},
        )

    # Record approved request metric
    execution_metrics.record_approved()

    LOGGER.info(
        "State transition",
        approval_id=claimed_request.approval_id,
        request_id=claimed_request.request_info.request_id,
        tool=claimed_request.request_info.tool_name,
        hash=claimed_request.payload_hash,
        transition="pending -> approved",
    )

    # 5. Transition APPROVED -> EXECUTING
    if not pending_store.mark_executing(nonce, operator_id=current_operator.id):
        monitoring_service.increment("approvals_replayed")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"message": "Already Executed"},
        )

    LOGGER.info(
        "State transition",
        approval_id=claimed_request.approval_id,
        request_id=claimed_request.request_info.request_id,
        tool=claimed_request.request_info.tool_name,
        hash=claimed_request.payload_hash,
        transition="approved -> executing",
    )

    # Create immutable execution context
    context = ExecutionContext(
        request_id=str(claimed_request.request_info.request_id or ""),
        approval_id=claimed_request.approval_id,
        operator=current_operator.username,
        request_fingerprint=claimed_request.payload_hash,
        execution_target=claimed_request.request_info.tool_name or "",
        status=ExecutionStatus.RUNNING,
    )

    # Emit ExecutionStarted audit event
    monitoring_service.increment("executions_total")
    emit_audit_event(
        db,
        ExecutionStarted,
        correlation_id=correlation_id,
        operator_id=current_operator.id,
        actor=current_operator.username,
        approval_id=claimed_request.approval_id,
        request_id=str(claimed_request.request_info.request_id or ""),
        status="executing",
        details={"tool": claimed_request.request_info.tool_name},
    )

    # 6. Execute request
    import inspect

    sig = inspect.signature(execution_engine.execute)
    exec_start = time.monotonic()

    # Propagate correlation ID to execution headers
    exec_headers = dict(claimed_request.headers)
    if correlation_id:
        exec_headers["X-Correlation-ID"] = correlation_id

    if "context" in sig.parameters:
        result = await execution_engine.execute(
            claimed_request.payload_bytes,
            exec_headers,
            context=context,
        )
    else:
        result = await execution_engine.execute(
            claimed_request.payload_bytes,
            exec_headers,
        )
    exec_latency_ms = (time.monotonic() - exec_start) * 1000.0

    # Record execution latency
    execution_metrics.record_execution_latency(exec_latency_ms)
    monitoring_service.observe("execution_duration_seconds", exec_latency_ms / 1000.0)

    # Record total approval latency
    approval_latency_ms = (time.monotonic() - start_time) * 1000.0
    execution_metrics.record_approval_latency(approval_latency_ms)

    # Bind execution ID to structlog contextvars if present in result
    exec_id = getattr(result, "execution_id", None) or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(execution_id=exec_id)

    # 7. Complete or Fail transition
    if result.success:
        pending_store.mark_completed(nonce, operator_id=current_operator.id)
        monitoring_service.increment("approvals_completed")
        monitoring_service.increment("executions_success")

        # Emit ExecutionFinished audit event
        emit_audit_event(
            db,
            ExecutionFinished,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            approval_id=claimed_request.approval_id,
            request_id=str(claimed_request.request_info.request_id or ""),
            latency=exec_latency_ms / 1000.0,
            status="completed",
            details={
                "execution_id": exec_id,
                "backend": result.backend,
                "status_code": result.status_code,
            },
        )

        LOGGER.info(
            "State transition",
            approval_id=claimed_request.approval_id,
            request_id=claimed_request.request_info.request_id,
            tool=claimed_request.request_info.tool_name,
            hash=claimed_request.payload_hash,
            transition="executing -> completed",
            duration_ms=exec_latency_ms,
            backend=result.backend,
            status=result.status_code,
        )
    else:
        pending_store.mark_failed(nonce, operator_id=current_operator.id)
        monitoring_service.increment("approvals_failed")
        monitoring_service.increment("executions_failure")
        if result.status_code == 504:
            monitoring_service.increment("executions_timeout")

        # Emit ExecutionFailed audit event
        emit_audit_event(
            db,
            ExecutionFailed,
            correlation_id=correlation_id,
            operator_id=current_operator.id,
            actor=current_operator.username,
            approval_id=claimed_request.approval_id,
            request_id=str(claimed_request.request_info.request_id or ""),
            latency=exec_latency_ms / 1000.0,
            status="failed",
            details={
                "execution_id": exec_id,
                "backend": result.backend,
                "status_code": result.status_code,
                "error_body": result.body.decode(errors="ignore")[:200],
            },
        )

        LOGGER.info(
            "State transition",
            approval_id=claimed_request.approval_id,
            request_id=claimed_request.request_info.request_id,
            tool=claimed_request.request_info.tool_name,
            hash=claimed_request.payload_hash,
            transition="executing -> failed",
            duration_ms=exec_latency_ms,
            backend=result.backend,
            status=result.status_code,
        )

    response = Response(content=result.body, status_code=result.status_code)
    for key, value in result.headers.items():
        response.headers[key] = value

    return response


@router.get("/pending", tags=["approve"])
async def get_pending(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.VIEW_PENDING))
    ],
) -> list[dict[str, Any]]:
    """Retrieve all currently active pending requests (not expired, not completed)."""
    from app.database.repositories import PendingRepository

    repo = PendingRepository(db)
    models = repo.get_pending_approvals()

    now = datetime.now(UTC).replace(tzinfo=None)
    active_models = []
    for m in models:
        # Only show requests that have not expired
        if m.expires_at > now:
            active_models.append(
                {
                    "nonce": m.nonce,
                    "approval_id": m.approval_id,
                    "tool": m.tool,
                    "operation": m.operation,
                    "namespace": m.namespace,
                    "resource": m.resource,
                    "created_at": m.created_at.isoformat(),
                    "expires_at": m.expires_at.isoformat(),
                    "status": m.status,
                }
            )
    return active_models


@router.get("/history", tags=["approve"])
async def get_history(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.VIEW_HISTORY))
    ],
) -> list[dict[str, Any]]:
    """Retrieve history of executed requests."""
    from app.database.repositories import ExecutionRepository

    repo = ExecutionRepository(db)
    records = repo.get_execution_history()
    return [
        {
            "execution_id": r.execution_id,
            "approval_id": r.approval_id,
            "status": r.status,
            "backend": r.backend,
            "started_at": r.started_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_ms": r.duration_ms,
            "http_status": r.http_status,
            "error_type": r.error_type,
            "retryable": r.retryable,
        }
        for r in records
    ]


@router.get("/audit", tags=["approve"])
async def get_audit(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.VIEW_AUDIT))
    ],
) -> list[dict[str, Any]]:
    """Retrieve audit events logs."""
    from app.database.repositories import AuditRepository

    repo = AuditRepository(db)
    events = repo.get_audit_history()
    return [
        {
            "event_id": e.event_id,
            "event_type": e.event_type,
            "actor": e.actor,
            "operator_id": e.operator_id,
            "recorded_at": e.recorded_at.isoformat(),
            "details": e.details,
        }
        for e in events
    ]


@router.post("/cleanup", tags=["admin"])
async def trigger_cleanup(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.MANAGE_SYSTEM))
    ],
) -> dict[str, Any]:
    """Manually trigger cleanup service to purge expired and completed requests."""
    from app.database.services import CleanupService

    cleanup_service = CleanupService(db)
    result = cleanup_service.run_cleanup()
    db.commit()
    return {"status": "success", "cleanup_results": result}


@router.get("/operators", response_model=list[OperatorSchema], tags=["admin"])
async def list_operators(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.MANAGE_USERS))
    ],
) -> Any:
    """List all registered operators."""
    from app.database.auth_services import OperatorService

    service = OperatorService(db)
    return service.list_operators()


@router.post("/operators", response_model=OperatorSchema, tags=["admin"])
async def create_operator(
    operator_in: OperatorCreate,
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.MANAGE_USERS))
    ],
) -> Any:
    """Create a new operator."""
    from app.database.auth_services import OperatorService

    service = OperatorService(db)
    if service.get_operator_by_username(operator_in.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )
    return service.create_operator(operator_in)


@router.delete("/operators/{operator_id}", tags=["admin"])
async def delete_operator(
    operator_id: int,
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[
        OperatorModel, Depends(require_permission(Permission.MANAGE_USERS))
    ],
) -> dict[str, Any]:
    """Delete an operator."""
    from app.database.auth_services import OperatorService

    service = OperatorService(db)
    if operator_id == current_operator.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )
    success = service.delete_operator(operator_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operator not found",
        )
    return {"status": "success", "message": f"Operator {operator_id} deleted"}
