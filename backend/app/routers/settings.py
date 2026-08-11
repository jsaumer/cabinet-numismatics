from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import ExchangeRate, Item, SpotPrice
from app.services import app_settings as store
from app.services import numista, pcgs

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
    value_strategy: Literal["latest", "preferred_source", "average"]
    preferred_source: Literal["melt", "numista", "pcgs"] | None
    numista_refresh_days: int | None
    pcgs_auto_refresh: bool
    numista_priceable_items: int
    pcgs_priceable_items: int
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
    value_strategy: Literal["latest", "preferred_source", "average"] | None = None
    preferred_source: Literal["melt", "numista", "pcgs"] | None = None
    numista_refresh_days: Literal[7, 14, 30] | None = None
    pcgs_auto_refresh: bool | None = None


def _priceable_counts(db: Session) -> tuple[int, int]:
    """Owned items eligible for Numista / PCGS pricing, reusing each
    adapter's own eligibility check rather than re-deriving it."""
    items = (
        db.execute(
            select(Item).where(Item.status == "owned").options(selectinload(Item.catalog_refs))
        )
        .scalars()
        .all()
    )
    numista_count = sum(1 for item in items if numista.type_id_for(item) is not None)
    pcgs_count = sum(
        1
        for item in items
        if pcgs.cert_number(item) is not None or pcgs.pcgs_number(item) is not None
    )
    return numista_count, pcgs_count


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
            available=True,
            secret_hint=store.secret_hint(pcgs_token),
            note="US coins by cert number, or PCGS number + grade. Auction sales when "
            "PCGS has them, price guide otherwise. Token from pcgs.com/publicapi "
            "(1,000 calls/day); responses cached 7 days.",
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

    numista_priceable, pcgs_priceable = _priceable_counts(db)
    return SettingsOut(
        display_currency=store.display_currency(db),
        reestimate_days=store.effective_reestimate_days(db),
        reestimate_days_overridden=store.get_setting(db, "reestimate_days") is not None,
        value_strategy=str(store.get_setting(db, "value_strategy")),
        preferred_source=store.get_setting(db, "preferred_source"),
        numista_refresh_days=store.get_setting(db, "numista_refresh_days"),
        pcgs_auto_refresh=bool(store.get_setting(db, "pcgs_auto_refresh")),
        numista_priceable_items=numista_priceable,
        pcgs_priceable_items=pcgs_priceable,
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
