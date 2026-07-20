# Repository & Service Design

This document details the architectural layout of the repository and service layers of the Veto Ops persistence system.

## Separation of Concerns
To keep the codebase clean, modular, and maintainable, Veto Ops enforces a strict separation of concerns:
1. **Model Layer (`models.py`)**: Defines ORM representation and database schemas.
2. **Repository Layer (`repositories.py`)**: Encapsulates raw SQLAlchemy query building, inserts, updates, and deletes. Business logic never enters this layer.
3. **Service Layer (`services.py`)**: Implements orchestration, transaction boundaries, signature validation, header redactions, audit event logging, and state transitions.

---

## Repositories

### `PendingRepository`
Responsible for managing intercepted MCP requests.
- `get_by_nonce(nonce: str)`: Fetches a request by its unique nonce.
- `get_by_approval_id(approval_id: str)`: Fetches a request by its unique approval identifier.
- `get_pending_approvals()`: Queries requests currently in a `"pending"` state.
- `add(model: PendingRequestModel)`: Adds a new request model.
- `delete(nonce: str)`: Deletes an request by its nonce.

### `ApprovalRepository`
Handles operator signature verifications and claim records.
- `add(model: ApprovalRecordModel)`: Persists an operator approval record.
- `get_by_approval_id(approval_id: str)`: Fetches the operator approval record matching an approval ID.

### `ExecutionRepository`
Handles the performance, duration, and error metrics of execution runs.
- `add(model: ExecutionRecordModel)`: Saves execution metrics.
- `get_failed_executions()`: Queries runs that returned retryable or fatal error statuses.

### `AuditRepository`
Maintains an append-only transaction log of all actions.
- `add(model: AuditEventModel)`: Appends a new immutable audit record.
- `get_audit_history()`: Retrieves all audit logs sorted chronologically.

---

## Services

- **`PersistenceService`**: Intercepts requests, redacts authorization headers, and persists them.
- **`ApprovalService`**: Performs signature verification and claims/updates the status from `pending` to `approved` atomically.
- **`ExecutionService`**: Manages execution state updates (`approved -> executing -> completed/failed`) inside database transactions.
- **`CleanupService`**: Periodically runs to delete expired pending requests and archive completed ones.
- **`AuditService`**: Logs state-transition and user events with structured payload metadata.
