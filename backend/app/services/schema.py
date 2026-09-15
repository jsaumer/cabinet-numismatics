"""The database schema revision: where the database is, what this build
expects, and bringing it up to date on startup.

Migrations still live in `alembic/` and still run through Alembic. This lets
the backend apply them itself before serving (AUTO_MIGRATE, on by default) and
report whether the database matches the code.
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


def alembic_config() -> Config:
    base = _backend_dir()
    config = Config(str(base / "alembic.ini"))
    config.set_main_option("script_location", str(base / "alembic"))
    return config


@cache
def script_revisions() -> tuple[str | None, frozenset[str]]:
    """The newest migration this build ships, and every revision it knows."""
    try:
        script = ScriptDirectory.from_config(alembic_config())
    except CommandError:
        return None, frozenset()
    return script.get_current_head(), frozenset(r.revision for r in script.walk_revisions())


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


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


def upgrade_to_head(engine: Engine) -> None:
    """Apply every pending migration in one transaction. On Postgres a failed
    migration rolls back entirely, and the exception stops startup."""
    wait_for_database(engine)
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
        before = current_revision(conn)
        config = alembic_config()
        config.attributes["connection"] = conn
        config.attributes["configure_logger"] = False  # keep the app's logging
        command.upgrade(config, "head")
        after = current_revision(conn)
    if before == after:
        logger.info("Database schema up to date (%s)", after)
    else:
        logger.info("Migrated database schema %s -> %s", before or "empty", after)
