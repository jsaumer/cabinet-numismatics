from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.db import engine
from app.services import documents, maintenance, schema

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    expected, known = schema.script_revisions()
    auth_expected, auth_known = schema.auth_script_revisions()
    current = auth_current = None
    if maintenance.active():
        # Don't touch the database: pg_restore holds exclusive locks, and a
        # health check that hangs gets the container killed mid-restore.
        return {
            "status": "ok",
            "db": "restoring",
            "version": __version__,
            "schema": schema.describe(None, expected, known, reachable=False),
            "auth_schema": schema.describe(None, auth_expected, auth_known, reachable=False),
            "documents": documents.storage_status(),
        }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            current = schema.current_revision(conn)
            auth_current = schema.current_auth_revision(conn)
        db = "ok"
    except Exception:
        db = "unreachable"
    return {
        "status": "ok",
        "db": db,
        "version": __version__,
        "schema": schema.describe(current, expected, known, reachable=db == "ok"),
        # The sign-in chain (cabinet_auth), migrated beside the collection's.
        "auth_schema": schema.describe(
            auth_current, auth_expected, auth_known, reachable=db == "ok"
        ),
        # ok | not_mounted (uploads refused) | unwritable
        "documents": documents.storage_status(),
    }
