"""Services for Authentication, Authorization (RBAC), and Operator management."""

from __future__ import annotations

from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy.orm import Session

from app.auth_models import (
    ROLE_PERMISSIONS,
    OperatorCreate,
    OperatorUpdate,
    Permission,
    UserRole,
)
from app.database.models import OperatorModel
from app.database.repositories import OperatorRepository

# Initialize Argon2 PasswordHasher
ph = PasswordHasher()


def hash_api_key(api_key: str) -> str:
    """Hash an API key using Argon2."""
    return ph.hash(api_key)


def verify_api_key(api_key_hash: str, api_key: str) -> bool:
    """Verify a plaintext API key against an Argon2 hash."""
    try:
        return ph.verify(api_key_hash, api_key)
    except VerifyMismatchError:
        return False


class OperatorService:
    """Service for managing Operators."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = OperatorRepository(db)

    def create_operator(self, operator_create: OperatorCreate) -> OperatorModel:
        """Create a new operator, hashing their API key with Argon2."""
        hashed_key = hash_api_key(operator_create.api_key)
        model = OperatorModel(
            username=operator_create.username,
            display_name=operator_create.display_name,
            email=operator_create.email,
            api_key_hash=hashed_key,
            role=str(operator_create.role),
            active=operator_create.active,
        )
        self.repo.add(model)
        self.db.commit()
        return model

    def get_operator(self, operator_id: int) -> OperatorModel | None:
        """Fetch an operator by ID."""
        return self.repo.get_by_id(operator_id)

    def get_operator_by_username(self, username: str) -> OperatorModel | None:
        """Fetch an operator by username."""
        return self.repo.get_by_username(username)

    def list_operators(self) -> list[OperatorModel]:
        """List all operators."""
        return self.repo.list_operators()

    def update_operator(
        self, operator_id: int, updates: OperatorUpdate
    ) -> OperatorModel | None:
        """Update operator details."""
        model = self.repo.get_by_id(operator_id)
        if not model:
            return None

        if updates.display_name is not None:
            model.display_name = updates.display_name
        if updates.email is not None:
            model.email = updates.email
        if updates.role is not None:
            model.role = str(updates.role)
        if updates.active is not None:
            model.active = updates.active

        model.updated_at = datetime.now(UTC).replace(tzinfo=None)
        self.db.commit()
        return model

    def delete_operator(self, operator_id: int) -> bool:
        """Delete an operator."""
        success = self.repo.delete(operator_id)
        if success:
            self.db.commit()
        return success

    def update_last_login(self, operator_id: int) -> None:
        """Update last login timestamp for an operator."""
        model = self.repo.get_by_id(operator_id)
        if model:
            model.last_login = datetime.now(UTC).replace(tzinfo=None)
            self.db.commit()


class AuthenticationService:
    """Service for authenticating operators."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = OperatorRepository(db)
        self.op_service = OperatorService(db)

    def authenticate_api_key(self, api_key: str) -> OperatorModel | None:
        """Authenticate an API key and return the matching active operator.

        Supports a fast hybrid lookup path if the API key contains a dot (prefix).
        Otherwise falls back to verifying against all active operators.
        """
        api_key = api_key.strip()
        if not api_key:
            return None

        # 1. Fast path: check if prefixed with username (e.g. username.key)
        if "." in api_key:
            prefix, _ = api_key.split(".", 1)
            operator = self.repo.get_by_username(prefix)
            if operator:
                if verify_api_key(operator.api_key_hash, api_key):
                    self.op_service.update_last_login(operator.id)
                    return operator
                return None

        # 2. Slow fallback path: scan all operators
        operators = self.repo.list_operators()
        for operator in operators:
            if verify_api_key(operator.api_key_hash, api_key):
                self.op_service.update_last_login(operator.id)
                return operator

        return None


class AuthorizationService:
    """Service for enforcing RBAC permissions."""

    @staticmethod
    def has_permission(operator: OperatorModel, permission: Permission) -> bool:
        """Check if an active operator has the specified permission."""
        if not operator.active:
            return False

        try:
            role = UserRole(operator.role)
        except ValueError:
            return False

        permissions = ROLE_PERMISSIONS.get(role, set())
        return permission in permissions
