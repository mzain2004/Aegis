"""Execution result models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ExecutionResult(BaseModel):
    """Structured result returned by a backend executor."""

    model_config = ConfigDict(extra="forbid")

    status_code: int = Field(description="HTTP status code from execution.")
    headers: dict[str, str] = Field(description="Response headers from upstream.")
    body: bytes = Field(description="Raw upstream response body.")
    latency_ms: int = Field(description="End-to-end execution latency in ms.")
    backend: str = Field(description="Execution backend name.")
    success: bool = Field(description="Whether execution completed successfully.")
