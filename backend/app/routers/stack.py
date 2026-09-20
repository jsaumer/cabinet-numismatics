from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import BackfillResult, StackReport
from app.services import stack
from app.services.app_settings import display_currency

router = APIRouter(prefix="/api/stack", tags=["stack"])


@router.get("", response_model=StackReport)
def stack_report(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    tag: str | None = Query(default=None, max_length=64),
    set_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Fine ounces, melt value at spot, cost per ounce (the break-even spot
    price), gain, and the premium paid over spot at purchase, per metal and per
    piece. Money is in one currency (the app-wide setting unless overridden);
    ounces count even when a piece's money can't be converted."""
    figures = stack.stack_figures(
        db, currency.upper() if currency else display_currency(db), tag, set_id
    )
    db.commit()  # keep any spot price or rate this request had to fetch
    return figures


@router.post("/backfill", response_model=BackfillResult)
def backfill_spot(db: Session = Depends(get_db)):
    """Look up the purchase-day spot price for pieces that qualify and have
    none. A figure typed in by hand is never touched."""
    return stack.backfill(db, stack.BACKFILL_LIMIT)
