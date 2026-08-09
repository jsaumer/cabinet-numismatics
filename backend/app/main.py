from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import get_settings
from app.routers import estimates, health, items, photos, reference, stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(get_settings().photo_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Cabinet API",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.include_router(health.router)
app.include_router(items.router)
app.include_router(photos.router)
app.include_router(estimates.router)
app.include_router(reference.router)
app.include_router(stats.router)
