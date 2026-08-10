from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.db import engine

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception:
        db = "unreachable"
    return {"status": "ok", "db": db, "version": __version__}
