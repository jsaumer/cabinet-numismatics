from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.db import engine
from app.services import schema

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    expected, known = schema.script_revisions()
    current = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = schema.current_revision(conn)
        db = "ok"
    except Exception:
        db = "unreachable"
    return {
        "status": "ok",
        "db": db,
        "version": __version__,
        "schema": schema.describe(current, expected, known, reachable=db == "ok"),
    }
