import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import get_settings
from app.models import Base  # noqa: F401 — registers all models on Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Arbitrary but stable application-wide key for the migration advisory lock.
_MIGRATION_LOCK_KEY = 210_226_651


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    # Every replica runs `alembic upgrade head` at start. Serialize them with
    # a session-level advisory lock so two replicas never race the same DDL;
    # the lock releases with the connection. SQLite (tests) has no advisory
    # locks and no replicas — skip.
    is_postgres = connection.dialect.name == "postgresql"
    if is_postgres:
        connection.exec_driver_sql(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_KEY})")
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        if is_postgres:
            connection.exec_driver_sql(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_KEY})")


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
