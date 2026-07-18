# Role-Based Access Control (RBAC) Design

Aegis enforces a strict Role-Based Access Control (RBAC) model to govern operator actions. Every request that goes through the approval router is evaluated against the authenticated operator's role and associated permission set.

## Roles and Permissions Matrix

Aegis defines three distinct operator roles: `viewer`, `approver`, and `administrator`.

| Permission | Description | Viewer | Approver | Administrator |
| :--- | :--- | :---: | :---: | :---: |
| `Permission.VIEW_PENDING` | View suspended requests | ✓ | ✓ | ✓ |
| `Permission.VIEW_HISTORY` | View executed requests logs | ✓ | ✓ | ✓ |
| `Permission.VIEW_AUDIT` | View system audit event logs | ✓ | ✓ | ✓ |
| `Permission.APPROVE_REQUEST` | Suspend / release approved request | ✗ | ✓ | ✓ |
| `Permission.MANAGE_SYSTEM` | Perform cleanup, config changes | ✗ | ✗ | ✓ |
| `Permission.MANAGE_USERS` | Add, update, delete operators | ✗ | ✗ | ✓ |

## Permission Architecture

Permissions are represented by the `Permission` StrEnum and roles are represented by the `UserRole` StrEnum.

### Definition snippet:
```python
class Permission(StrEnum):
    VIEW_PENDING = "view_pending"
    VIEW_HISTORY = "view_history"
    VIEW_AUDIT = "view_audit"
    APPROVE_REQUEST = "approve_request"
    MANAGE_SYSTEM = "manage_system"
    MANAGE_USERS = "manage_users"

class UserRole(StrEnum):
    VIEWER = "viewer"
    APPROVER = "approver"
    ADMINISTRATOR = "administrator"
```

## Policy Enforcement (FastAPI Dependencies)

RBAC policy checks are applied as decorators directly on FastAPI routes:

```python
@router.post("/cleanup")
async def trigger_cleanup(
    db: Annotated[Session, Depends(get_db)],
    current_operator: Annotated[OperatorModel, Depends(require_permission(Permission.MANAGE_SYSTEM))]
):
    ...
```

The `require_permission` dependency operates as follows:
1. Resolves the current operator via `get_current_operator`.
2. Inspects the operator's role.
3. Obtains the allowed permissions set for the operator's role.
4. Checks if the required permission is present in the allowed set.
5. If absent, raises `HTTP 403 Forbidden` with a detailed error message listing the missing required permission.
