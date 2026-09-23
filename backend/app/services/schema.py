"""The database schema revision: where the database is, what this build
expects, and bringing it up to date on startup.

Migrations still live in `alembic/` and still run through Alembic. This lets
the backend apply them itself before serving (AUTO_MIGRATE, on by default) and
report whether the database matches the code.

Two chains (v0.30.0): the collection's (`alembic/`, schema `public`) and the
sign-in chain (`alembic_auth/`, schema `cabinet_auth`, its version table
inside that schema). They never touch each other's schema; startup runs the
collection chain and then the sign-in chain in one transaction.
"""

import logging
import time
from functools import cache
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import OperationalError

from alembic import command

logger = logging.getLogger(__name__)

# Fixed key for pg_advisory_xact_lock, so two backends starting at once can't
# both migrate. Cabinet should run one backend anyway; the lock is cheap.
MIGRATION_LOCK_KEY = 7340512
DB_WAIT_SECONDS = 60


def _backend_dir() -> Path:
    # backend/app/services/schema.py → backend/, where alembic.ini lives in a
    # checkout and in the image. If `app` was imported from an install
    # elsewhere, fall back to the working directory.
    source = Path(__file__).resolve().parents[2]
    return source if (source / "alembic.ini").is_file() else Path.cwd()


AUTH_SCHEMA = "cabinet_auth"


def alembic_config(auth: bool = False) -> Config:
    base = _backend_dir()
    name = "alembic_auth" if auth else "alembic"
    config = Config(str(base / f"{name}.ini"))
    config.set_main_option("script_location", str(base / name))
    return config


def _revisions(auth: bool) -> tuple[str | None, frozenset[str]]:
    try:
        script = ScriptDirectory.from_config(alembic_config(auth))
    except CommandError:
        return None, frozenset()
    return script.get_current_head(), frozenset(r.revision for r in script.walk_revisions())


@cache
def script_revisions() -> tuple[str | None, frozenset[str]]:
    """The newest collection migration this build ships, and every one it knows."""
    return _revisions(auth=False)


@cache
def auth_script_revisions() -> tuple[str | None, frozenset[str]]:
    """The same for the sign-in chain."""
    return _revisions(auth=True)


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def current_auth_revision(connection: Connection) -> str | None:
    """The sign-in chain's revision, from its own version table; None before
    the schema exists."""
    context = MigrationContext.configure(
        connection,
        opts={"version_table": "alembic_version", "version_table_schema": AUTH_SCHEMA},
    )
    return context.get_current_revision()


def describe(
    current: str | None, expected: str | None, known: frozenset[str], reachable: bool
) -> dict:
    if not reachable or expected is None:
        state = "unknown"
    elif current == expected:
        state = "ok"
    elif current is not None and current not in known:
        state = "ahead"  # migrated by a newer build than this one
    else:
        state = "pending"
    return {"current": current, "expected": expected, "status": state}


def wait_for_database(engine: Engine, timeout: float = DB_WAIT_SECONDS) -> None:
    """Swarm gives no startup ordering, so the backend can start before
    Postgres accepts connections. Wait for it rather than fail on first try."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if time.monotonic() >= deadline:
                raise
            logger.info("Database not reachable yet; retrying")
            time.sleep(2)


def _upgrade(conn: Connection, auth: bool) -> None:
    config = alembic_config(auth)
    config.attributes["connection"] = conn
    config.attributes["configure_logger"] = False  # keep the app's logging
    command.upgrade(config, "head")


def upgrade_to_head(engine: Engine, auth: bool = True) -> None:
    """Apply every pending migration in one transaction: the collection chain,
    then (unless `auth` is false) the sign-in chain. On Postgres a failed
    migration rolls back entirely, and the exception stops startup. A restore
    migrates the collection only: it never touched the sign-in chain."""
    wait_for_database(engine)
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        before = current_revision(conn)
        _upgrade(conn, auth=False)
        after = current_revision(conn)
        if auth:
            auth_before = current_auth_revision(conn)
            _upgrade(conn, auth=True)
            auth_after = current_auth_revision(conn)
    if before == after:
        logger.info("Database schema up to date (%s)", after)
    else:
        logger.info("Migrated database schema %s -> %s", before or "empty", after)
    if auth and auth_before != auth_after:
        logger.info("Migrated sign-in schema %s -> %s", auth_before or "empty", auth_after)
