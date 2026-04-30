"""
GAD database layer — engine, session factory, and initialization helpers.

The default backend is a single SQLite file at backend/gad.db. Override with
the GAD_DATABASE_URL environment variable (used by the test suite to point
at an in-memory SQLite database). The schema is versioned with Alembic;
init_db() applies pending migrations and then seeds reference data.

Usage:

    from db import init_db, get_session
    from db.models import State

    init_db()                                # safe to call multiple times
    with get_session() as db:
        florida = db.get(State, 'FL')

Schema-change workflow:
    1. Edit backend/db/models.py.
    2. `alembic revision --autogenerate -m "describe change"`.
    3. Hand-review the generated file in alembic/versions/.
    4. Commit. Next app boot applies the migration automatically.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Default location: backend/gad.db (same directory as this package's parent).
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "gad.db"
_DEFAULT_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

DATABASE_URL = os.environ.get("GAD_DATABASE_URL", _DEFAULT_URL)

# Repo root, used to locate alembic.ini regardless of the cwd the app is
# started from.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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


def _alembic_config():
    """Build an Alembic Config pointing at the repo-root alembic.ini, with
    sqlalchemy.url overridden to the live DATABASE_URL so CLI runs and
    in-process boots agree."""
    from alembic.config import Config

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    # Resolve script_location to an absolute path so this works no matter
    # which directory the app was launched from.
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


def init_db(seed: bool = True) -> None:
    """Idempotently apply Alembic migrations and (optionally) seed reference data.

    Migrations are applied via `alembic.command.upgrade(cfg, "head")`. The
    application's existing engine connection is passed in via
    `Config.attributes["connection"]` so the migration runs against the
    same database the app uses — critical for in-memory SQLite tests
    where a fresh engine would target a different :memory: database.

    Called once at app import time and once per pytest session. Safe to
    invoke repeatedly: Alembic skips already-applied revisions and the
    seed function short-circuits when the `states` table is non-empty.
    """
    from alembic import command

    cfg = _alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")

    if seed:
        from .seed import seed_database
        with get_session() as db:
            seed_database(db)


__all__ = ["engine", "SessionLocal", "get_session", "init_db", "DATABASE_URL"]
