# Migration Report

This document reports on the database migration layout, configuration, and rollback strategies.

## Migration Tooling
Aegis uses **Alembic** for schema migrations. Alembic is configured to run programmatically or via CLI, using a dynamically resolved database connection string sourced directly from the application's configuration module.

- **Config Path**: `alembic.ini`
- **Migration Scripts Directory**: `alembic/versions/`

---

## Initial Schema Migration
The initial database schema was generated using:
```bash
alembic revision --autogenerate -m "initial_schema"
```
The migration script is stored in `alembic/versions/ab9fec45bd4e_initial_schema.py`.

### Target Tables Created
1. `pending_requests`
2. `approval_records`
3. `execution_records`
4. `audit_events`

### Schema Constraints and Indexes
- **Unique Constraints**: `pending_requests.nonce`, `pending_requests.approval_id`, and `approval_records.approval_id`.
- **Foreign Keys**:
  - `approval_records.approval_id` references `pending_requests.approval_id` with `ON DELETE CASCADE`.
  - `execution_records.approval_id` references `pending_requests.approval_id` with `ON DELETE CASCADE`.
- **Indexes**:
  - `ix_pending_requests_nonce` (Unique Index)
  - `ix_pending_requests_approval_id` (Unique Index)
  - `ix_pending_requests_created_at`
  - `ix_pending_requests_expires_at`
  - `ix_pending_requests_status`
  - `ix_audit_events_recorded_at`
  - `ix_audit_events_event_type`

---

## Upgrade and Rollback Operations

### Upgrading Schema to Latest Version
To execute all pending migrations and bring the database schema to the latest version, run:
```bash
alembic upgrade head
```

### Rollback (Downgrading Schema)
To revert the last applied migration:
```bash
alembic downgrade -1
```
To drop all tables and revert to base:
```bash
alembic downgrade base
```
