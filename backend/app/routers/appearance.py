"""The colour theme (v0.35.0): a display choice saved on the server so it
follows the owner to every device. Its own endpoint, like the dashboard
layout, so changing it doesn't ask for the password again the way a
Settings change does. The frontend's themes (frontend/src/themes.ts) must
list exactly these keys."""

from typing import Literal, get_args

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.permissions import permission
from app.db import get_db
from app.services import app_settings as store

router = APIRouter(prefix="/api/appearance", tags=["appearance"])

Theme = Literal["bronze", "silver", "album", "ledger"]
THEMES: tuple[str, ...] = get_args(Theme)


class AppearanceOut(BaseModel):
    theme: Theme
    themes: list[str]


class AppearanceUpdate(BaseModel):
    theme: Theme


def _current(db: Session) -> str:
    """The stored theme, or the default when what's stored isn't one any more
    (an archive from a later release that added a theme, say)."""
    theme = store.get_setting(db, "ui_theme")
    return theme if theme in THEMES else store.DEFAULTS["ui_theme"]


@router.get("", response_model=AppearanceOut)
@permission("read")
def get_appearance(db: Session = Depends(get_db)):
    return {"theme": _current(db), "themes": list(THEMES)}


@router.put("", response_model=AppearanceOut)
@permission("admin")
def set_appearance(payload: AppearanceUpdate, db: Session = Depends(get_db)):
    store.set_setting(db, "ui_theme", payload.theme)
    db.commit()
    return {"theme": payload.theme, "themes": list(THEMES)}
