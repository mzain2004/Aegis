"""Pydantic models for the Veto Ops proxy."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.rpc_parser import MCPRequestInfo


class RequestStatus(StrEnum):
    """The state of a suspended request in the approval pipeline."""

    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class PendingRequest(BaseModel):
    """Represents a request suspended for future review."""

    model_config = ConfigDict(extra="forbid")

    nonce: str = Field(description="Unique identifier for the suspended request.")
    payload_hash: str = Field(description="SHA256 hash of the raw request bytes.")
    payload_bytes: bytes = Field(description="Raw request body bytes.")
    headers: dict[str, str] = Field(description="Captured request headers.")
    request_info: MCPRequestInfo = Field(description="Parsed MCP request metadata.")
    created_at: datetime = Field(description="Timestamp when the request was stored.")
    expires_at: datetime = Field(description="Timestamp when the request expires.")
    status: RequestStatus = Field(
        default=RequestStatus.PENDING,
        description="Current state of the suspended request.",
    )
    approval_id: str = Field(
        default="",
        description="Stable approval identifier returned to client.",
    )


class ApprovalRequest(BaseModel):
    """Represents a human approval decision request."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="Pending request identifier.")
    approved_by: str = Field(description="Person or system responsible for review.")
    reason: str | None = Field(
        default=None,
        description="Optional explanation for the approval decision.",
    )
    requested_at: datetime = Field(description="Time the approval was requested.")


class ApprovalResponse(BaseModel):
    """Represents the outcome of a future approval workflow."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(description="Pending request identifier.")
    approved: bool = Field(description="Whether the request was approved.")
    message: str = Field(description="Human-readable response message.")
    processed_at: datetime = Field(description="Time the response was generated.")


class AuditLog(BaseModel):
    """Represents a future audit trail entry for proxy activity."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(description="Unique audit event identifier.")
    event_type: str = Field(description="Category of the audit event.")
    actor: str | None = Field(
        default=None,
        description="Optional principal associated with the event.",
    )
    recorded_at: datetime = Field(description="Time the audit event was written.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured audit context for later phases.",
    )


class ProxyMetadata(BaseModel):
    """Describes the runtime identity of the proxy service."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(description="Canonical service name.")
    version: str = Field(description="Service version string.")
    environment: str = Field(description="Deployment environment label.")
    host: str = Field(description="Configured bind host.")
    port: int = Field(description="Configured bind port.")
