"""Alembic environment. The URL comes from Settings, never from alembic.ini."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from backend.common.config import get_settings
from backend.common.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def _guard_test_database() -> None:
    """In test mode (ELO_TESTING=1) only the throwaway elo_test database may be migrated."""
    if os.environ.get("ELO_TESTING") == "1" and get_settings().db_name != "elo_test":
        raise RuntimeError("ELO_TESTING=1: refusing to migrate any database except elo_test")


def run_migrations_offline() -> None:
    _guard_test_database()
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    _guard_test_database()
    connectable = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
