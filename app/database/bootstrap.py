"""Database bootstrap logic to initialize default data (e.g., admin user)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth_models import OperatorCreate, UserRole
from app.config import get_settings
from app.database.auth_services import OperatorService
from app.database.repositories import OperatorRepository


def bootstrap_database(db: Session) -> None:
    """Ensure database has at least one admin operator if empty."""
    repo = OperatorRepository(db)
    operators = repo.list_operators()
    if not operators:
        settings = get_settings()
        op_service = OperatorService(db)

        # Create default admin operator
        admin_create = OperatorCreate(
            username=settings.default_admin_username,
            display_name="Default Administrator",
            email="admin@aegis.local",
            role=UserRole.ADMINISTRATOR,
            active=True,
            api_key=settings.default_admin_apikey,
        )
        op_service.create_operator(admin_create)
