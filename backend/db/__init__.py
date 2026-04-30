"""
GAD database layer — engine, session factory, and initialization helpers.

The default backend is a single SQLite file at backend/gad.db. Override with
the GAD_DATABASE_URL environment variable (used by the test suite to point
at an in-memory SQLite database). All static reference data is auto-seeded
on first startup; subsequent boots are idempotent.

Usage:

    from db import init_db, get_session
    from db.models import State

    init_db()                                # safe to call multiple times
    with get_session() as db:
        florida = db.get(State, 'FL')

Future work (tracked in DESIGN.md §15): swap auto-create + seed for Alembic
migrations once the schema starts evolving.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

# Default location: backend/gad.db (same directory as this package's parent).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "gad.db"
_DEFAULT_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

DATABASE_URL = os.environ.get("GAD_DATABASE_URL", _DEFAULT_URL)


def _make_engine(url: str):
    """Build the engine. In-memory SQLite needs a StaticPool so the schema
    persists across the connections opened by Flask test-client requests."""
    if url.startswith("sqlite:///:memory:") or url == "sqlite://":
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    return create_engine(url, future=True)


engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session():
    """Per-request session context manager. Caller-scoped lifetime; commits
    are explicit (we don't write at request time today). Always closes."""
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(seed: bool = True) -> None:
    """Idempotently create all tables and (optionally) seed reference data.

    Called once at app import time and once per pytest session. Safe to
    invoke repeatedly — `create_all` skips existing tables and the seed
    function short-circuits when the `states` table is already populated.
    """
    Base.metadata.create_all(bind=engine)
    if seed:
        from .seed import seed_database
        with get_session() as db:
            seed_database(db)


__all__ = ["engine", "SessionLocal", "get_session", "init_db", "DATABASE_URL"]
