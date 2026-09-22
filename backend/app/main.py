import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import __version__
from app.config import ConfigError, check_startup, get_settings
from app.db import engine
from app.routers import (
    backup,
    catalogue,
    checklists,
    comparables,
    dashboard,
    documents,
    estimates,
    health,
    imports,
    items,
    monitoring,
    photos,
    pricing_reports,
    reference,
    restore,
    settings,
    stack,
    stats,
    trash,
)
from app.services import archive_keys, scheduled, schema
from app.services import backup as backups
from app.services import restore as restores
from app.services.maintenance import MaintenanceMiddleware

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """uvicorn only configures its own loggers, so without this the app's INFO
    lines (migrations, scheduled refreshes) never reach the container log.
    Scoped to `app` and `alembic`: the root logger at INFO would also dump
    every SQL statement and outbound HTTP request."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:     %(name)s - %(message)s"))
    for name in ("app", "alembic"):
        named = logging.getLogger(name)
        if not named.handlers:
            named.addHandler(handler)
            named.setLevel(logging.INFO)
            named.propagate = False


_configure_logging()


def _in_session(task) -> None:
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        task(db)
    finally:
        db.close()


async def _reestimation_loop() -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            await asyncio.to_thread(_in_session, scheduled.refresh)
        except Exception:
            logger.exception("Scheduled refresh failed")


async def _hourly_loop() -> None:
    # Hourly checks against the last run, so a daily backup survives restarts
    # and a failed one is retried within the hour; the same tick empties the
    # trash and pushes the heartbeat. The first waits a few minutes so a fresh
    # deploy settles before archiving.
    await asyncio.sleep(300)
    while True:
        try:
            await asyncio.to_thread(_in_session, scheduled.hourly)
        except Exception:
            logger.exception("Hourly task failed")
        await asyncio.sleep(3600)


def _check_key_against_record(db) -> None:
    """Say loudly if the newest archive this Cabinet recorded was made with a
    key it no longer has: the key was replaced or lost, and those archives
    can't be restored here until it is put back."""
    from app.services import alerts

    try:
        missing = backups.record_key_mismatch(db)
    except Exception:
        logger.exception("Could not check the backup key against the archive record")
        return
    if missing:
        message = (
            f"The newest backup was made with a key this Cabinet no longer has ({missing}). "
            "Put the old key back (BACKUP_KEY_FILE, or the backup.key you saved) or those "
            "archives can't be restored."
        )
        logger.critical(message)
        alerts.event(db, "backup_key_changed", "Cabinet's backup key changed", message)


def _key_location_messages() -> list[str]:
    """Said on every start: where the keys sit relative to the backups.
    Silence is never presented as a safety result."""
    messages = []
    where = archive_keys.location()
    if where in archive_keys.LOCATION_MESSAGES:
        messages.append(archive_keys.LOCATION_MESSAGES[where])
    secret_where = archive_keys.secret_key_location()
    if secret_where == "shared":
        messages.append(
            "The generated SECRET_KEY file is stored beside your backups; set SECRET_KEY "
            "or move the state volume."
        )
    elif secret_where == "not_verified":
        messages.append(
            "Cabinet cannot tell where the generated SECRET_KEY file is stored relative to "
            "your backups; setting SECRET_KEY removes the doubt."
        )
    return messages


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_settings()
    # Deployment settings first: a missing or wrong one stops startup here,
    # with a message naming the variable, before anything is served.
    try:
        warnings = check_startup(config)
    except ConfigError as exc:
        logger.critical("Cabinet cannot start: %s", exc)
        raise
    for warning in warnings:
        logger.warning(warning)
    # The backup key: a supplied one that can't be read stops startup here,
    # before any backup could be written; otherwise one is generated.
    try:
        await asyncio.to_thread(archive_keys.ensure_key)
    except ConfigError as exc:
        logger.critical("Cabinet cannot start: %s", exc)
        raise
    for message in _key_location_messages():
        logger.warning(message)
    try:
        await asyncio.to_thread(backups.self_test)
    except backups.BackupError as exc:
        logger.critical("Backups will fail: %s", exc)
    Path(config.photo_dir).mkdir(parents=True, exist_ok=True)
    # A restore the last process didn't finish: roll its file swap forward,
    # or clear what it had unpacked.
    await asyncio.to_thread(restores.recover)
    if config.auto_migrate:
        # Before serving anything: new code must not run against an old schema.
        # A failure raises here and stops startup rather than limping along.
        await asyncio.to_thread(schema.upgrade_to_head, engine)
        # A secret stored as plain text is never used; clear and name it now
        # rather than at the first hourly tick. Tests (AUTO_MIGRATE=false)
        # have no database here; the hourly tick covers that setting too.
        await asyncio.to_thread(_in_session, scheduled.clear_secrets)
        await asyncio.to_thread(_in_session, _check_key_against_record)
    # The loop always runs; each cycle re-reads the cadence setting, so
    # changing it in Settings takes effect without a restart.
    tasks = [asyncio.create_task(_reestimation_loop()), asyncio.create_task(_hourly_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    title="Cabinet API",
    version=__version__,
    lifespan=lifespan,
    # No interactive docs page: it would run a third-party script in the
    # signed-in origin. The schema stays at /api/openapi.json.
    docs_url=None,
    redoc_url=None,
    swagger_ui_oauth2_redirect_url=None,
    openapi_url="/api/openapi.json",
)

# While a restore runs, everything but health and the restore status is 503.
app.add_middleware(MaintenanceMiddleware)

app.include_router(health.router)
app.include_router(items.router)
app.include_router(photos.router)
app.include_router(estimates.router)
app.include_router(estimates.refresh_router)
app.include_router(reference.router)
app.include_router(stats.router)
app.include_router(checklists.router)
app.include_router(settings.router)
app.include_router(backup.router)
app.include_router(catalogue.router)
app.include_router(catalogue.pcgs_router)
app.include_router(pricing_reports.router)
app.include_router(comparables.router)
app.include_router(imports.router)
app.include_router(documents.router)
app.include_router(trash.router)
app.include_router(monitoring.router)
app.include_router(restore.router)
app.include_router(dashboard.router)
app.include_router(stack.router)
