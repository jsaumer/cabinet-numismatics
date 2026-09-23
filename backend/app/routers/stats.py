from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.permissions import permission
from app.db import get_db
from app.models import Item
from app.schemas import (
    BreakdownEntry,
    Breakdowns,
    CollectionStats,
    DataHealth,
    GainEntry,
    Gains,
    NotesBySignature,
    QualityStats,
    Showcase,
    ValueHistory,
    ValuePoint,
    ValueSpread,
)
from app.services import insights
from app.services.app_settings import display_currency, get_setting
from app.services.currency import Converter
from app.services.pricing import detect_metal, resolve_display_value


def _resolve_currency(db: Session, currency: str | None) -> str:
    """Explicit ?currency= wins; otherwise the app-wide display currency."""
    return currency.upper() if currency else display_currency(db)


def _resolve_strategy(db: Session) -> tuple[str, str | None]:
    return str(get_setting(db, "value_strategy")), get_setting(db, "preferred_source")


router = APIRouter(prefix="/api/stats", tags=["stats"])

UNDATED = "Undated"  # the decade bucket for a piece with no year


def _load_items(db: Session) -> list[Item]:
    return (
        db.execute(select(Item).options(selectinload(Item.estimates), selectinload(Item.tags)))
        .scalars()
        .all()
    )


@router.get("/collection", response_model=CollectionStats)
@permission("read", metrics_ok=True)
def collection_stats(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Collection totals in one display currency (the app-wide setting unless
    overridden). Other currencies are converted at cached daily rates;
    amounts with no obtainable rate are excluded and counted, never guessed."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    items = _load_items(db)

    counts = {
        "total": len(items),
        "owned": 0,
        "sold": 0,
        "wishlist": 0,
        "coins": 0,
        "notes": 0,
        "bullion": 0,
    }
    cost_basis = 0.0
    estimated_value = 0.0
    unrealized = 0.0
    realized = 0.0
    estimated_items = 0

    for item in items:
        counts[item.status] += 1
        if item.status == "owned":  # the split describes the current holdings
            if item.type == "coin":
                counts["coins"] += 1
            elif item.type == "note":
                counts["notes"] += 1
            else:
                counts["bullion"] += 1
        resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)

        if item.status == "owned":
            price = conv.convert(item.cost_basis, item.currency)
            est = conv.convert(resolved[0], resolved[1]) if resolved else None
            if price is not None:
                cost_basis += price
            if est is not None:
                estimated_value += est
                estimated_items += 1
            if price is not None and est is not None:
                unrealized += est - price
        elif item.status == "sold":
            price = conv.convert(item.cost_basis, item.currency)
            sold = conv.convert(item.sale_proceeds, item.currency)
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
@permission("read")
def breakdowns(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tag: str | None = Query(default=None, max_length=64),
    set_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Owned items grouped by country, type, decade, grade, and tag, plus
    acquisitions by year. Counts include every owned item; money sums are
    converted into the display currency (unconvertible amounts excluded).
    `tag` / `set_id` scope every breakdown to items carrying that tag or
    belonging to that set; an unknown tag or set gives empty breakdowns,
    not an error."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    dims: dict[str, dict[str, _Bucket]] = {
        d: defaultdict(_Bucket)
        for d in ("country", "type", "decade", "grade", "tag", "metal", "acq_year")
    }

    for item in _load_items(db):
        if item.status != "owned":
            continue
        if tag is not None and not any(t.name == tag for t in item.tags):
            continue
        if set_id is not None and item.set_id != set_id:
            continue
        resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)
        cost = conv.convert(item.cost_basis, item.currency) or 0.0
        value = (conv.convert(resolved[0], resolved[1]) if resolved else None) or 0.0

        keys = {
            "country": [item.country],
            "type": [item.type],
            "decade": [UNDATED if item.year is None else f"{(item.year // 10) * 10}s"],
            "grade": [item.grade.code if item.grade else "ungraded"],
            "tag": [t.name for t in item.tags],
            "metal": [(detect_metal(item.composition) or "other").title()],
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
        # Undated pieces are their own bucket, after the decades.
        by_decade=[
            _entry(k, b)
            for k, b in sorted(dims["decade"].items(), key=lambda kv: (kv[0] == UNDATED, kv[0]))
        ],
        by_grade=[_entry(k, b) for k, b in sorted(dims["grade"].items(), key=by_value)],
        by_tag=[_entry(k, b) for k, b in sorted(dims["tag"].items(), key=by_value)],
        by_metal=[_entry(k, b) for k, b in sorted(dims["metal"].items(), key=by_value)],
        acquisitions_by_year=[_entry(k, b) for k, b in sorted(dims["acq_year"].items())],
    )


@router.get("/gains", response_model=Gains)
@permission("read")
def gains(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Per-item gain/loss in the display currency (converted where needed):
    unrealized for owned items with both a price and an estimate, realized for
    sold items."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    unrealized: list[GainEntry] = []
    realized: list[GainEntry] = []

    for item in _load_items(db):
        cost = conv.convert(item.cost_basis, item.currency)
        if cost is None:
            continue
        if item.status == "owned":
            resolved = resolve_display_value(item.estimates, strategy, preferred_source, conv)
            value = conv.convert(resolved[0], resolved[1]) if resolved else None
        elif item.status == "sold":
            value = conv.convert(item.sale_proceeds, item.currency)
        else:
            continue
        if value is None:
            continue
        entry = GainEntry(
            item_id=item.id,
            label=item.label,
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
@permission("read")
def value_history(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    months: int = Query(default=24, ge=1, le=120),
    db: Session = Depends(get_db),
):
    """Collection value at each month-end: per owned item, the latest estimate
    on or before that date (converted at today's cached rates: historical
    rates are out of scope for a personal tool)."""
    currency = _resolve_currency(db, currency)
    conv = Converter(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    items = [i for i in _load_items(db) if i.status == "owned"]

    points = []
    for point in _month_ends(months):
        total = 0.0
        count = 0
        for item in items:
            # estimates are newest-first; keep only what existed as of this point,
            # then resolve the same way "now" is resolved elsewhere.
            asof = [e for e in item.estimates if e.fetched_at.date() <= point]
            resolved = resolve_display_value(asof, strategy, preferred_source, conv)
            value = conv.convert(resolved[0], resolved[1]) if resolved else None
            if value is not None:
                total += value
                count += 1
        points.append(ValuePoint(date=point, value=round(total, 2), estimated_items=count))

    # drop leading months before any estimate existed
    first = next((i for i, p in enumerate(points) if p.estimated_items > 0), len(points))
    return ValueHistory(currency=currency, points=points[first:])


@router.get("/notes-by-signature", response_model=NotesBySignature)
@permission("read")
def notes_by_signature(db: Session = Depends(get_db)):
    """Owned notes grouped by series and signature pair: groups by series then
    signatures (those without come last), notes by serial number."""
    notes = (
        db.execute(select(Item).where(Item.type == "note", Item.status == "owned")).scalars().all()
    )
    groups: dict[tuple, list[Item]] = defaultdict(list)
    for note in notes:
        groups[(note.series or None, note.signatures or None)].append(note)

    def nulls_last(text: str | None) -> tuple:
        return (text is None, (text or "").lower())

    return {
        "groups": [
            {
                "series": series,
                "signatures": signatures,
                "count": len(members),
                "quantity": sum(n.quantity for n in members),
                "items": [
                    {
                        "id": n.id,
                        "label": n.label,
                        "serial_number": n.serial_number,
                        "grade_label": n.grade_label,
                    }
                    for n in sorted(members, key=lambda n: nulls_last(n.serial_number))
                ],
            }
            for (series, signatures), members in sorted(
                groups.items(), key=lambda kv: (nulls_last(kv[0][0]), nulls_last(kv[0][1]))
            )
        ],
        "total": len(notes),
    }


@router.get("/quality", response_model=QualityStats)
@permission("read")
def quality(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Certified vs. raw owned items, by count and value, plus a breakdown
    by grading service."""
    currency = _resolve_currency(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    return insights.quality_stats(db, currency, strategy, preferred_source)


@router.get("/value-spread", response_model=ValueSpread)
@permission("read")
def value_spread(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """min/median/max/mean of owned items' shown values, and the share of
    total value held by the top 10% of pieces."""
    currency = _resolve_currency(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    return insights.value_spread(db, currency, strategy, preferred_source)


@router.get("/data-health", response_model=DataHealth)
@permission("read")
def data_health(db: Session = Depends(get_db)):
    """Owned items missing a photo, grade, cost, value estimate,
    weight/fineness, storage location, or catalogue reference."""
    return insights.data_health(db)


@router.get("/showcase", response_model=Showcase)
@permission("read")
def showcase(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Piece of the day, oldest and newest pieces, and pieces acquired on
    this day in an earlier year."""
    currency = _resolve_currency(db, currency)
    strategy, preferred_source = _resolve_strategy(db)
    return insights.showcase(db, currency, strategy, preferred_source)
