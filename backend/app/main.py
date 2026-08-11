import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app import __version__
from app.config import get_settings
from app.routers import checklists, estimates, health, items, photos, reference, settings, stats

logger = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(get_settings().photo_dir).mkdir(parents=True, exist_ok=True)
    # The loop always runs; each cycle re-reads the cadence setting, so
    # changing it in Settings takes effect without a restart.
    task = asyncio.create_task(_reestimation_loop())
    yield
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
