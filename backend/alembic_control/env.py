"""Alembic env for the control-plane database.

Mirrors the per-tenant ``alembic/env.py`` shape but binds to
``ControlBase.metadata`` and uses ``settings.control_database_url``.
The two trees are intentionally separate so a control-plane migration
cannot accidentally run against a tenant database (or vice versa).
"""
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make the app package importable when running alembic from the backend/ dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.models.control import ControlBase  # noqa: F401 — registers control tables

config = context.config

# Override the placeholder URL with the control-plane URL from app
# settings. This is what makes `alembic -c alembic_control.ini` always
# target the control DB regardless of the file's default.
config.set_main_option("sqlalchemy.url", settings.control_database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = ControlBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
