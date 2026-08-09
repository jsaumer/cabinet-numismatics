from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Item
from app.schemas import BreakdownEntry, Breakdowns, CollectionStats, GainEntry, Gains

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
    currency: str = Query(default="USD", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Collection totals in one declared display currency (no conversion —
    rows in other currencies are excluded and counted)."""
    currency = currency.upper()
    items = _load_items(db)

    counts = {"total": len(items), "owned": 0, "sold": 0, "wishlist": 0, "coins": 0, "notes": 0}
    cost_basis = 0.0
    estimated_value = 0.0
    unrealized = 0.0
    realized = 0.0
    estimated_items = 0
    excluded = 0

    for item in items:
        counts[item.status] += 1
        if item.status == "owned":  # coins/notes split describes the current holdings
            counts["coins" if item.type == "coin" else "notes"] += 1
        latest = item.estimates[0] if item.estimates else None

        if item.status == "owned":
            price_ok = item.acquisition_price is not None and item.currency == currency
            est_ok = latest is not None and latest.currency == currency
            if item.acquisition_price is not None and item.currency != currency:
                excluded += 1
            elif latest is not None and latest.currency != currency:
                excluded += 1
            if price_ok:
                cost_basis += float(item.acquisition_price)
            if est_ok:
                estimated_value += float(latest.estimated_value)
                estimated_items += 1
            if price_ok and est_ok:
                unrealized += float(latest.estimated_value) - float(item.acquisition_price)
        elif item.status == "sold":
            if item.sold_price is None or item.acquisition_price is None:
                continue
            if item.currency != currency:
                excluded += 1
                continue
            realized += float(item.sold_price) - float(item.acquisition_price)

    return CollectionStats(
        currency=currency,
        counts=counts,
        cost_basis=round(cost_basis, 2),
        estimated_value=round(estimated_value, 2),
        unrealized_gain=round(unrealized, 2),
        realized_gain=round(realized, 2),
        estimated_items=estimated_items,
        excluded_other_currency=excluded,
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
    currency: str = Query(default="USD", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Owned items grouped by country, type, decade, grade, and tag, plus
    acquisitions by year. Counts include every owned item; money sums follow
    the display-currency rule."""
    currency = currency.upper()
    dims: dict[str, dict[str, _Bucket]] = {
        d: defaultdict(_Bucket) for d in ("country", "type", "decade", "grade", "tag", "acq_year")
    }

    for item in _load_items(db):
        if item.status != "owned":
            continue
        latest = item.estimates[0] if item.estimates else None
        cost = (
            float(item.acquisition_price)
            if item.acquisition_price is not None and item.currency == currency
            else 0.0
        )
        value = (
            float(latest.estimated_value)
            if latest is not None and latest.currency == currency
            else 0.0
        )

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
    currency: str = Query(default="USD", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Per-item gain/loss in the display currency: unrealized for owned items
    with both a price and an estimate, realized for sold items."""
    currency = currency.upper()
    unrealized: list[GainEntry] = []
    realized: list[GainEntry] = []

    for item in _load_items(db):
        if item.currency != currency or item.acquisition_price is None:
            continue
        cost = float(item.acquisition_price)
        if item.status == "owned":
            latest = item.estimates[0] if item.estimates else None
            if latest is None or latest.currency != currency:
                continue
            value = float(latest.estimated_value)
            unrealized.append(
                GainEntry(
                    item_id=item.id,
                    label=_item_label(item),
                    cost_basis=cost,
                    value=value,
                    gain=round(value - cost, 2),
                )
            )
        elif item.status == "sold" and item.sold_price is not None:
            value = float(item.sold_price)
            realized.append(
                GainEntry(
                    item_id=item.id,
                    label=_item_label(item),
                    cost_basis=cost,
                    value=value,
                    gain=round(value - cost, 2),
                )
            )

    unrealized.sort(key=lambda e: -e.gain)
    realized.sort(key=lambda e: -e.gain)
    return Gains(currency=currency, unrealized=unrealized, realized=realized)
