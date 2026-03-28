"""Database engine and session factory.

Supports PostgreSQL (production) and SQLite (testing).
Set DATABASE_URL in .env — e.g.:
  postgresql://just_agentic:just_agentic@localhost:5432/just_agentic
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_url(raw: str) -> str:
    """Normalize DATABASE_URL to SQLAlchemy dialect format."""
    if raw.startswith("postgres://"):
        # Heroku-style legacy URL
        raw = raw.replace("postgres://", "postgresql://", 1)
    if raw.startswith("postgresql://") and "+psycopg" not in raw and "+psycopg2" not in raw:
        # Default to psycopg2 driver for broad compatibility
        raw = raw.replace("postgresql://", "postgresql+psycopg2://", 1)
    return raw


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise RuntimeError(
                "DATABASE_URL is not set. "
                "Copy .env.example → .env and configure your PostgreSQL connection."
            )
        _engine = create_engine(_build_url(url), pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False
        )
    return _SessionLocal


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager — commits on success, rolls back on exception."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
