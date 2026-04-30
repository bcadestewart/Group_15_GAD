"""
Alembic environment for GAD.

Two ways this file is invoked:

1. CLI usage during development:
     `alembic revision --autogenerate -m "..."`
     `alembic upgrade head`
   In this mode, `engine_from_config` builds a fresh engine from
   alembic.ini (with GAD_DATABASE_URL overriding the URL if set).

2. Programmatic usage at app boot:
     init_db() in backend/db/__init__.py opens a transaction on the
     application's existing engine, stuffs the connection into
     Config.attributes['connection'], and calls command.upgrade.
   This avoids the classic Alembic + in-memory SQLite trap where
   Alembic's own engine would target a different :memory: database.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ─── Make backend/ importable so we can import db.models ────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from db.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the URL from the GAD_DATABASE_URL env var when set, so CLI usage
# matches the app's runtime configuration.
if os.environ.get("GAD_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["GAD_DATABASE_URL"])

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without connecting to a database (used by `--sql` flag)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection.

    Prefers a pre-existing connection passed via Config.attributes (the
    init_db() programmatic path) so we don't spin up a second engine
    against an in-memory SQLite database — that would create a fresh DB
    that the application engine never sees.
    """
    connection = config.attributes.get("connection")

    if connection is None:
        # CLI path — build a new engine from alembic.ini.
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with connectable.connect() as conn:
            _do_run_migrations(conn)
    else:
        # Programmatic path — reuse the application's connection.
        _do_run_migrations(connection)


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Render SQLite-friendly batch ops automatically when needed.
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
