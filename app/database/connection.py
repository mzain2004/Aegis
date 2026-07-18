"""Database engine and session management."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# Retrieve settings
settings = get_settings()

# Configure SQLite specifically for better concurrency
connect_args: dict[str, Any] = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30.0

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)


# Active connection counter
_active_db_connections = 0
_db_connections_lock = threading.Lock()


# Enable WAL mode and foreign keys on SQLite connections
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore
    if context:
        context._query_start_time = time.monotonic()


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # type: ignore
    from app.monitoring.metrics import monitoring_service

    monitoring_service.increment("db_queries_total")
    if context and hasattr(context, "_query_start_time"):
        duration = time.monotonic() - context._query_start_time
        monitoring_service.observe("db_transaction_duration", duration)


@event.listens_for(engine, "checkout")
def pool_checkout(dbapi_connection, connection_record, connection_proxy):  # type: ignore
    global _active_db_connections
    from app.monitoring.metrics import monitoring_service

    with _db_connections_lock:
        _active_db_connections += 1
    monitoring_service.gauge("db_pool_connections", _active_db_connections)


@event.listens_for(engine, "checkin")
def pool_checkin(dbapi_connection, connection_record):  # type: ignore
    global _active_db_connections
    from app.monitoring.metrics import monitoring_service

    with _db_connections_lock:
        _active_db_connections = max(0, _active_db_connections - 1)
    monitoring_service.gauge("db_pool_connections", _active_db_connections)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db_session() -> Generator[Session, None, None]:
    """Dependency for obtaining a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
