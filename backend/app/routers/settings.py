from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ExchangeRate, SpotPrice
from app.services import app_settings as store

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SourceStatus(BaseModel):
    key: str
    name: str
    enabled: bool
    configured: bool  # credentials present (always true for keyless sources)
    available: bool  # adapter implemented in this build
    secret_hint: str | None = None
    note: str | None = None


class CachedValue(BaseModel):
    label: str
    value: str
    source: str
    fetched_at: datetime


class SettingsOut(BaseModel):
    display_currency: str
    reestimate_days: int  # effective value (DB override or env default)
    reestimate_days_overridden: bool
    sources: list[SourceStatus]
    cached: list[CachedValue]


class SettingsUpdate(BaseModel):
    display_currency: str | None = Field(default=None, min_length=3, max_length=3)
    reestimate_days: int | None = Field(default=None, ge=0, le=365)
    melt_enabled: bool | None = None
    numista_enabled: bool | None = None
    numista_api_key: str | None = Field(default=None, max_length=200)  # "" clears
    pcgs_enabled: bool | None = None
    pcgs_api_token: str | None = Field(default=None, max_length=500)  # "" clears


def _build(db: Session) -> SettingsOut:
    numista_key = str(store.get_setting(db, "numista_api_key"))
    pcgs_token = str(store.get_setting(db, "pcgs_api_token"))
    sources = [
        SourceStatus(
            key="melt",
            name="Melt value (spot × weight × fineness)",
            enabled=bool(store.get_setting(db, "melt_enabled")),
            configured=True,
            available=True,
            note="Keyless — spot prices from gold-api.com, cached 12h.",
        ),
        SourceStatus(
            key="numista",
            name="Numista price estimates (coins + notes)",
            enabled=bool(store.get_setting(db, "numista_enabled")),
            configured=bool(numista_key),
            available=True,
            secret_hint=store.secret_hint(numista_key),
            note="Priced by numista catalog ref + grade. Free API key at numista.com "
            "(2,000 requests/month); responses cached 7–30 days.",
        ),
        SourceStatus(
            key="pcgs",
            name="PCGS price guide + auction prices (US coins)",
            enabled=bool(store.get_setting(db, "pcgs_enabled")),
            configured=bool(pcgs_token),
            available=False,
            secret_hint=store.secret_hint(pcgs_token),
            note="Adapter arrives with pricing program M3. Token from pcgs.com/publicapi.",
        ),
    ]

    cached = [
        CachedValue(
            label=f"{row.metal} spot",
            value=f"{float(row.price_per_gram):.4f} {row.currency}/g",
            source=row.source,
            fetched_at=row.fetched_at,
        )
        for row in db.execute(select(SpotPrice).order_by(SpotPrice.metal)).scalars()
    ] + [
        CachedValue(
            label=f"{row.base}→{row.quote}",
            value=f"{float(row.rate):.4f}",
            source=row.source,
            fetched_at=row.fetched_at,
        )
        for row in db.execute(
            select(ExchangeRate).order_by(ExchangeRate.base, ExchangeRate.quote)
        ).scalars()
    ]

    return SettingsOut(
        display_currency=store.display_currency(db),
        reestimate_days=store.effective_reestimate_days(db),
        reestimate_days_overridden=store.get_setting(db, "reestimate_days") is not None,
        sources=sources,
        cached=cached,
    )


@router.get("", response_model=SettingsOut)
def get_app_settings(db: Session = Depends(get_db)):
    return _build(db)


@router.put("", response_model=SettingsOut)
def update_app_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    fields = payload.model_dump(exclude_unset=True)
    if "display_currency" in fields:
        fields["display_currency"] = fields["display_currency"].upper()
    for key, value in fields.items():
        store.set_setting(db, key, value)
    db.commit()
    return _build(db)
