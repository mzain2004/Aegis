"""Pydantic schemas and enums for Authentication and RBAC."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Permission(StrEnum):
    """Permissions available within Veto Ops."""

    VIEW_PENDING = "view_pending"
    VIEW_HISTORY = "view_history"
    APPROVE_REQUEST = "approve_request"
    EXECUTE_REQUEST = "execute_request"
    MANAGE_USERS = "manage_users"
    MANAGE_SYSTEM = "manage_system"
    VIEW_METRICS = "view_metrics"
    VIEW_AUDIT = "view_audit"


class UserRole(StrEnum):
    """Operator roles available within Veto Ops."""

    VIEWER = "viewer"
    APPROVER = "approver"
    ADMINISTRATOR = "administrator"


# Mapping of roles to their explicit permissions
ROLE_PERMISSIONS: dict[UserRole, set[Permission]] = {
    UserRole.VIEWER: {
        Permission.VIEW_PENDING,
        Permission.VIEW_HISTORY,
        Permission.VIEW_AUDIT,
        Permission.VIEW_METRICS,
    },
    UserRole.APPROVER: {
        Permission.VIEW_PENDING,
        Permission.VIEW_HISTORY,
        Permission.VIEW_AUDIT,
        Permission.VIEW_METRICS,
        Permission.APPROVE_REQUEST,
    },
    UserRole.ADMINISTRATOR: {
        Permission.VIEW_PENDING,
        Permission.VIEW_HISTORY,
        Permission.VIEW_AUDIT,
        Permission.VIEW_METRICS,
        Permission.APPROVE_REQUEST,
        Permission.EXECUTE_REQUEST,
        Permission.MANAGE_USERS,
        Permission.MANAGE_SYSTEM,
    },
}


class OperatorSchema(BaseModel):
    """Pydantic representation of an Operator."""

    id: int
    username: str
    display_name: str
    email: str
    role: UserRole
    active: bool
    created_at: datetime
    updated_at: datetime
    last_login: datetime | None = None

    model_config = {"from_attributes": True}


class OperatorCreate(BaseModel):
    """Schema for creating a new Operator."""

    username: str = Field(min_length=3, max_length=50)
    display_name: str = Field(min_length=1, max_length=100)
    email: str
    role: UserRole
    active: bool = True
    api_key: str = Field(description="Plaintext API key to hash and store")


class OperatorUpdate(BaseModel):
    """Schema for updating an Operator."""

    display_name: str | None = None
    email: str | None = None
    role: UserRole | None = None
    active: bool | None = None
