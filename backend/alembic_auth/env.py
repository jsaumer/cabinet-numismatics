"""Alembic environment for the sign-in chain: the `cabinet_auth` schema only.

Its own version table lives inside that schema, and `include_name` keeps
autogenerate from ever reflecting another schema. The backend runs this
chain itself right after the collection's, in the same transaction and under
the same advisory lock (`app.services.schema.upgrade_to_head`).
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from app.config import get_settings
from app.models.auth import SCHEMA, AuthBase

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url)

target_metadata = AuthBase.metadata


def include_name(name, type_, parent_names) -> bool:
    return name == SCHEMA if type_ == "schema" else True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table="alembic_version",
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        **kwargs,
    )


def _migrate(connection) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    _configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:  # passed in by upgrade_to_head, which commits
        _migrate(connection)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _migrate(connection)
        # CREATE SCHEMA began the transaction, so Alembic treats it as the
        # caller's and leaves the commit to us.
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
