"""
Test configuration — sets up a SQLite test database for all tests.
Called automatically by pytest before any test collection.
"""

import os
import pytest

# Set DATABASE_URL to an in-memory SQLite DB before any imports touch db/session.py
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_just_agentic.db")
os.environ.setdefault("JWT_SECRET", "test-secret-for-pytest")


def pytest_configure(config):
    """Create tables and seed default data once per test session."""
    from db import init_db
    init_db()


def pytest_sessionfinish(session, exitstatus):
    """Clean up test database file after the session."""
    import pathlib
    db_file = pathlib.Path("./test_just_agentic.db")
    if db_file.exists():
        db_file.unlink()
