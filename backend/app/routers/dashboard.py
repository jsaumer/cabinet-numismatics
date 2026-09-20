"""The customisable dashboard layout (roadmap Phase 7, P10). See
services/dashboard.py for the widget table and the read/write rules."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import app_settings as store
from app.services import dashboard

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class WidgetOut(BaseModel):
    id: str
    type: str
    size: str
    title: str | None
    options: dict


class LayoutOut(BaseModel):
    version: int
    widgets: list[WidgetOut]
    is_default: bool


class LayoutUpdate(BaseModel):
    widgets: list[dict]


@router.get("/layout", response_model=LayoutOut)
def get_layout(db: Session = Depends(get_db)):
    stored = store.get_setting(db, "dashboard_layout")
    layout, is_default = dashboard.normalize_for_read(stored)
    return {**layout, "is_default": is_default}


@router.put("/layout", response_model=LayoutOut)
def save_layout(payload: LayoutUpdate, db: Session = Depends(get_db)):
    try:
        widgets = dashboard.validate_widgets(payload.widgets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    layout = {"version": dashboard.CURRENT_VERSION, "widgets": widgets}
    store.set_setting(db, "dashboard_layout", layout)
    db.commit()
    return {**layout, "is_default": False}


@router.delete("/layout", response_model=LayoutOut)
def reset_layout(db: Session = Depends(get_db)):
    store.set_setting(db, "dashboard_layout", None)
    db.commit()
    layout, is_default = dashboard.normalize_for_read(None)
    return {**layout, "is_default": is_default}
