# Veto Ops Authentication and Schema Migration Guide

This document outlines the steps required to upgrade existing Veto Ops database schemas to include operator authentication, role-based access control, and audit references.

## 1. Database Schema Alterations

The authentication system introduces:
- A new `operators` table.
- Nullable foreign key relationships on `approval_records` and `audit_events` referencing `operators.id`.

### SQLite Compatibilities
Because SQLite does not support standard `ALTER TABLE ADD CONSTRAINT` commands for adding foreign key relationships to existing tables, the Alembic migration scripts utilize Alembic batch mode copy-and-move strategies:

```python
with op.batch_alter_table("approval_records", schema=None) as batch_op:
    batch_op.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
    batch_op.create_foreign_key(
        "fk_approval_records_operator_id",
        "operators",
        ["operator_id"],
        ["id"],
        ondelete="SET NULL",
    )
```

## 2. Running Schema Migrations

To apply schema upgrades to the Veto Ops database:

```bash
# Apply migrations to the head revision
alembic upgrade head
```

If you need to roll back:

```bash
# Roll back one migration step
alembic downgrade -1
```

The migration version identifier is: `9cb22dd7adfe_add_operators_and_auth_relations.py`

## 3. Database Seeding & Bootstrapping

Veto Ops includes a self-healing bootstrap seeder to prevent lockout when authentication is first enabled.
- **Trigger**: Application startup checks if the `operators` table is empty.
- **Action**: If empty, a default administrator account is seeded using credentials defined in the application configuration.
- **Environment Variables**:
  - `DEFAULT_ADMIN_USERNAME`: Defaults to `admin`.
  - `DEFAULT_ADMIN_APIKEY`: Defaults to `admin-api-key-12345`.

## 4. Configuration Adjustments

To enable/disable authentication in different environments, apply the following keys to your configuration profile or shell environment:

```env
# Enable authentication logic (true/false)
AUTH_ENABLED=true

# Allow anonymous access in dev environments (true/false)
ALLOW_ANONYMOUS_DEV=false

# Default admin seeder configuration (Optional)
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_APIKEY=admin-api-key-12345
```
