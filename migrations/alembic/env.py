from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool


config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None


def mysql_url() -> str:
    user = os.environ.get("GAMEOPS_MYSQL_USER", "gameops")
    password = os.environ.get("GAMEOPS_MYSQL_PASSWORD", "gameops-pass")
    host = os.environ.get("GAMEOPS_MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("GAMEOPS_MYSQL_PORT", "3306")
    database = os.environ.get("GAMEOPS_MYSQL_DATABASE", "gameops")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


def run_migrations_offline() -> None:
    context.configure(
        url=mysql_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(mysql_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
