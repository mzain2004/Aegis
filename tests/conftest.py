"""Pytest configuration and database isolation fixtures."""

from __future__ import annotations

import os
import tempfile

import pytest
from sqlalchemy import create_engine

from app.config import get_settings
from app.database import connection
from app.database.models import Base


@pytest.fixture(autouse=True, scope="function")
def configure_test_db():
    """Isolate each test to a clean temporary SQLite file database."""
    # Create a unique temporary file path for SQLite
    temp_dir = tempfile.gettempdir()
    db_file_path = os.path.join(temp_dir, f"test_veto_ops_{os.getpid()}.db")
    db_url = f"sqlite:///{db_file_path.replace(os.sep, '/')}"

    settings = get_settings()
    original_db_url = settings.database_url
    original_auth_enabled = settings.auth_enabled
    settings.database_url = db_url
    settings.auth_enabled = False

    # Swap out connection engine & session maker for test run
    old_engine = connection.engine

    # Configure SQLite for test
    connect_args = {"check_same_thread": False}
    connection.engine = create_engine(
        db_url,
        connect_args=connect_args,
    )
    connection.SessionLocal.configure(bind=connection.engine)

    # Create all tables according to DB models schema
    Base.metadata.create_all(bind=connection.engine)

    yield

    # Clean up and restore state
    Base.metadata.drop_all(bind=connection.engine)
    connection.engine.dispose()

    # Safely remove the test database file
    if os.path.exists(db_file_path):
        try:
            os.remove(db_file_path)
        except Exception:
            pass

    connection.engine = old_engine
    connection.SessionLocal.configure(bind=old_engine)
    settings.database_url = original_db_url
    settings.auth_enabled = original_auth_enabled
