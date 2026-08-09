from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Item
from app.schemas import (
    BreakdownEntry,
    Breakdowns,
    CollectionStats,
    GainEntry,
    Gains,
    ValueHistory,
    ValuePoint,
)
from app.services.app_settings import display_currency
from app.services.currency import Converter


def _resolve_currency(db: Session, currency: str | None) -> str:
    """Explicit ?currency= wins; otherwise the app-wide display currency."""
    return currency.upper() if currency else display_currency(db)


router = APIRouter(prefix="/api/stats", tags=["stats"])


def _item_label(item: Item) -> str:
    parts = [item.country, item.denomination, str(item.year)]
    if item.mint_mark:
        parts.append(f'"{item.mint_mark}"')
    return " ".join(parts)


def _load_items(db: Session) -> list[Item]:
    return (
        db.execute(select(Item).options(selectinload(Item.estimates), selectinload(Item.tags)))
        .scalars()
        .all()
    )


@router.get("/collection", response_model=CollectionStats)
def collection_stats(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Collection totals in one display currency (the app-wide setting unless
    overridden). Other currencies are converted at cached daily rates;
    amounts with no obtainable rate are excluded and counted, never guessed."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    items = _load_items(db)

    counts = {"total": len(items), "owned": 0, "sold": 0, "wishlist": 0, "coins": 0, "notes": 0}
    cost_basis = 0.0
    estimated_value = 0.0
    unrealized = 0.0
    realized = 0.0
    estimated_items = 0

    for item in items:
        counts[item.status] += 1
        if item.status == "owned":  # coins/notes split describes the current holdings
            counts["coins" if item.type == "coin" else "notes"] += 1
        latest = item.estimates[0] if item.estimates else None

        if item.status == "owned":
            price = conv.convert(item.acquisition_price, item.currency)
            est = conv.convert(latest.estimated_value, latest.currency) if latest else None
            if price is not None:
                cost_basis += price
            if est is not None:
                estimated_value += est
                estimated_items += 1
            if price is not None and est is not None:
                unrealized += est - price
        elif item.status == "sold":
            price = conv.convert(item.acquisition_price, item.currency)
            sold = conv.convert(item.sold_price, item.currency)
            if price is not None and sold is not None:
                realized += sold - price

    return CollectionStats(
        currency=currency,
        counts=counts,
        cost_basis=round(cost_basis, 2),
        estimated_value=round(estimated_value, 2),
        unrealized_gain=round(unrealized, 2),
        realized_gain=round(realized, 2),
        estimated_items=estimated_items,
        converted_other_currency=conv.converted,
        excluded_other_currency=conv.excluded,
    )


class _Bucket:
    __slots__ = ("count", "cost", "value")

    def __init__(self):
        self.count = 0
        self.cost = 0.0
        self.value = 0.0


def _entry(key: str, b: _Bucket) -> BreakdownEntry:
    return BreakdownEntry(
        key=key, count=b.count, cost_basis=round(b.cost, 2), estimated_value=round(b.value, 2)
    )


@router.get("/breakdowns", response_model=Breakdowns)
def breakdowns(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Owned items grouped by country, type, decade, grade, and tag, plus
    acquisitions by year. Counts include every owned item; money sums are
    converted into the display currency (unconvertible amounts excluded)."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    dims: dict[str, dict[str, _Bucket]] = {
        d: defaultdict(_Bucket) for d in ("country", "type", "decade", "grade", "tag", "acq_year")
    }

    for item in _load_items(db):
        if item.status != "owned":
            continue
        latest = item.estimates[0] if item.estimates else None
        cost = conv.convert(item.acquisition_price, item.currency) or 0.0
        value = (conv.convert(latest.estimated_value, latest.currency) if latest else None) or 0.0

        keys = {
            "country": [item.country],
            "type": [item.type],
            "decade": [f"{(item.year // 10) * 10}s"],
            "grade": [item.grade.code if item.grade else "ungraded"],
            "tag": [t.name for t in item.tags],
            "acq_year": ([str(item.acquisition_date.year)] if item.acquisition_date else []),
        }
        for dim, dim_keys in keys.items():
            for key in dim_keys:
                bucket = dims[dim][key]
                bucket.count += 1
                bucket.cost += cost
                bucket.value += value

    by_value = lambda kv: (-kv[1].value, -kv[1].count, kv[0])  # noqa: E731
    return Breakdowns(
        currency=currency,
        by_country=[_entry(k, b) for k, b in sorted(dims["country"].items(), key=by_value)],
        by_type=[_entry(k, b) for k, b in sorted(dims["type"].items(), key=by_value)],
        by_decade=[_entry(k, b) for k, b in sorted(dims["decade"].items())],
        by_grade=[_entry(k, b) for k, b in sorted(dims["grade"].items(), key=by_value)],
        by_tag=[_entry(k, b) for k, b in sorted(dims["tag"].items(), key=by_value)],
        acquisitions_by_year=[_entry(k, b) for k, b in sorted(dims["acq_year"].items())],
    )


@router.get("/gains", response_model=Gains)
def gains(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Per-item gain/loss in the display currency (converted where needed):
    unrealized for owned items with both a price and an estimate, realized for
    sold items."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    unrealized: list[GainEntry] = []
    realized: list[GainEntry] = []

    for item in _load_items(db):
        cost = conv.convert(item.acquisition_price, item.currency)
        if cost is None:
            continue
        if item.status == "owned":
            latest = item.estimates[0] if item.estimates else None
            value = conv.convert(latest.estimated_value, latest.currency) if latest else None
        elif item.status == "sold":
            value = conv.convert(item.sold_price, item.currency)
        else:
            continue
        if value is None:
            continue
        entry = GainEntry(
            item_id=item.id,
            label=_item_label(item),
            cost_basis=round(cost, 2),
            value=round(value, 2),
            gain=round(value - cost, 2),
        )
        (unrealized if item.status == "owned" else realized).append(entry)

    unrealized.sort(key=lambda e: -e.gain)
    realized.sort(key=lambda e: -e.gain)
    return Gains(currency=currency, unrealized=unrealized, realized=realized)


def _month_ends(months: int) -> list[date]:
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()  # estimates are stored in UTC
    points = []
    for i in range(months - 1, -1, -1):
        ym = today.year * 12 + (today.month - 1) - i
        year, month = divmod(ym, 12)
        if month == 11:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 2, 1)
        points.append(min(end - timedelta(days=1), today))
    return points


@router.get("/value-history", response_model=ValueHistory)
def value_history(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    months: int = Query(default=24, ge=1, le=120),
    db: Session = Depends(get_db),
):
    """Collection value at each month-end: per owned item, the latest estimate
    on or before that date (converted at today's cached rates — historical
    rates are out of scope for a personal tool)."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    items = [i for i in _load_items(db) if i.status == "owned"]

    # per item: estimates as (date, converted value), oldest first
    series: list[list[tuple[date, float]]] = []
    for item in items:
        entries = []
        for est in reversed(item.estimates):  # relationship is newest-first
            value = conv.convert(est.estimated_value, est.currency)
            if value is not None:
                entries.append((est.fetched_at.date(), value))
        if entries:
            series.append(entries)

    points = []
    for point in _month_ends(months):
        total = 0.0
        count = 0
        for entries in series:
            current = None
            for est_date, value in entries:
                if est_date <= point:
                    current = value
                else:
                    break
            if current is not None:
                total += current
                count += 1
        points.append(ValuePoint(date=point, value=round(total, 2), estimated_items=count))

    # drop leading months before any estimate existed
    first = next((i for i, p in enumerate(points) if p.estimated_items > 0), len(points))
    return ValueHistory(currency=currency, points=points[first:])
