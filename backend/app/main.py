import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.db import engine
from app.routers import (
    backup,
    checklists,
    estimates,
    health,
    items,
    photos,
    reference,
    settings,
    stats,
)
from app.services import schema

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """uvicorn only configures its own loggers, so without this the app's INFO
    lines (migrations, scheduled refreshes) never reach the container log.
    Scoped to `app` and `alembic` — the root logger at INFO would also dump
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


def _run_scheduled_refresh() -> None:
    from app.db import SessionLocal
    from app.services.app_settings import effective_reestimate_days, get_setting
    from app.services.pricing import refresh_melt_estimates, refresh_source_estimates

    db = SessionLocal()
    try:
        days = effective_reestimate_days(db)
        if days <= 0 or not get_setting(db, "melt_enabled"):
            logger.info("Scheduled melt refresh disabled (days=%s)", days)
        else:
            logger.info("Scheduled melt refresh: %s", refresh_melt_estimates(db, days))

        numista_days = get_setting(db, "numista_refresh_days")
        if numista_days and get_setting(db, "numista_enabled"):
            logger.info(
                "Scheduled numista refresh: %s",
                refresh_source_estimates(db, "numista", int(numista_days)),
            )

        if get_setting(db, "pcgs_auto_refresh") and get_setting(db, "pcgs_enabled"):
            logger.info("Scheduled pcgs refresh: %s", refresh_source_estimates(db, "pcgs", 7))
    finally:
        db.close()


async def _reestimation_loop() -> None:
    while True:
        await asyncio.sleep(12 * 3600)
        try:
            await asyncio.to_thread(_run_scheduled_refresh)
        except Exception:
            logger.exception("Scheduled refresh failed")


def _run_scheduled_backup() -> None:
    from app.db import SessionLocal
    from app.services import backup as backups

    db = SessionLocal()
    try:
        outcome = backups.run_scheduled(db)
        if outcome:
            logger.info("Scheduled backup: %s", outcome)
    except backups.BackupError as exc:
        logger.error("Scheduled backup failed: %s", exc)
    finally:
        db.close()


async def _backup_loop() -> None:
    # Hourly checks against the last run, so a daily backup survives restarts
    # and a failed one is retried within the hour. The first check waits a few
    # minutes so a fresh deploy settles before archiving.
    await asyncio.sleep(300)
    while True:
        try:
            await asyncio.to_thread(_run_scheduled_backup)
        except Exception:
            logger.exception("Scheduled backup failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_settings()
    Path(config.photo_dir).mkdir(parents=True, exist_ok=True)
    if config.auto_migrate:
        # Before serving anything: new code must not run against an old schema.
        # A failure raises here and stops startup rather than limping along.
        await asyncio.to_thread(schema.upgrade_to_head, engine)
    # The loop always runs; each cycle re-reads the cadence setting, so
    # changing it in Settings takes effect without a restart.
    tasks = [asyncio.create_task(_reestimation_loop()), asyncio.create_task(_backup_loop())]
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(
    title="Cabinet API",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

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
