# Database Architecture

This document describes the design of the database persistence layer for **Veto Ops**.

## Technology Stack
- **ORM**: SQLAlchemy 2.x using fully annotated PEP-597 declarative mapping models (`Mapped[...]` and `mapped_column()`).
- **Database Engine**: SQLite by default, structured with 100% standard SQL syntax to allow seamless transition to PostgreSQL or other enterprise RDBMS via the `DATABASE_URL` setting.
- **Migrations**: Alembic for declarative schema version control and schema upgrade paths.

## Concurrency Optimizations
To support reliable performance under high concurrent loads (e.g., during high frequency AI agent requests) using SQLite, the following optimizations were applied:
1. **WAL (Write-Ahead Logging)**: Enabled dynamically on connection creation via `PRAGMA journal_mode=WAL;`. This allows concurrent readers and writers without blocking each other.
2. **Foreign Key Constraints**: Enforced at the engine connection level via `PRAGMA foreign_keys=ON;`.
3. **Optimistic Locking / Atomic Status Updates**: All state machine transitions (`PENDING -> APPROVED -> EXECUTING -> COMPLETED/FAILED`) are performed using atomic `UPDATE` statements matching the expected current state (e.g., `.where(status="pending")`). If no rows are modified (`rowcount == 0`), the transaction rolls back and returns an error reason, guaranteeing exactly-once processing (replay protection).

## Security & Data Redaction
- **Header Redaction**: Sensitive client headers (e.g., `Authorization`, `Cookie`, `X-API-Key`) are redacted at the service layer prior to database insertion.
- **Secret Redaction**: Symmetric HMAC secrets and signature verifications are computed in-memory; credentials and verification secrets are never stored in the database.
