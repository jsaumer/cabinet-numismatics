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
    catalogue,
    checklists,
    comparables,
    documents,
    estimates,
    health,
    imports,
    items,
    monitoring,
    photos,
    pricing_reports,
    reference,
    settings,
    stats,
    trash,
)
from app.services import scheduled, schema

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
    tasks = [asyncio.create_task(_reestimation_loop()), asyncio.create_task(_hourly_loop())]
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
app.include_router(catalogue.router)
app.include_router(catalogue.pcgs_router)
app.include_router(pricing_reports.router)
app.include_router(comparables.router)
app.include_router(imports.router)
app.include_router(documents.router)
app.include_router(trash.router)
app.include_router(monitoring.router)
