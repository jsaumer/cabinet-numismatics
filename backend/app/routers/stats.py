from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Item
from app.schemas import CollectionStats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/collection", response_model=CollectionStats)
def collection_stats(
    currency: str = Query(default="USD", min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Collection totals in one declared display currency (no conversion —
    rows in other currencies are excluded and counted)."""
    currency = currency.upper()
    items = db.execute(select(Item).options(selectinload(Item.estimates))).scalars().all()

    counts = {"total": len(items), "owned": 0, "sold": 0, "wishlist": 0, "coins": 0, "notes": 0}
    cost_basis = 0.0
    estimated_value = 0.0
    unrealized = 0.0
    realized = 0.0
    estimated_items = 0
    excluded = 0

    for item in items:
        counts[item.status] += 1
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
