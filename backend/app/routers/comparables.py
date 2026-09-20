"""The per-item sales log behind the `comps` estimate (v0.17.0)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Comparable
from app.routers.items import get_item_or_404
from app.schemas import ComparableCreate, ComparableOut, ComparableUpdate, SalesFetchResult
from app.services import numista
from app.services.pricing import NotApplicable, SourceUnavailable

router = APIRouter(tags=["comparables"])

REQUIRED = ("sold_on", "venue", "price", "currency")
MONEY = ("price", "fees")


def _get_or_404(db: Session, comparable_id: int) -> Comparable:
    row = db.get(Comparable, comparable_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Sale not found")
    return row


def _money(fields: dict) -> dict:
    return {
        key: Decimal(str(value)) if key in MONEY and value is not None else value
        for key, value in fields.items()
    }


@router.get("/api/items/{item_id}/comparables", response_model=list[ComparableOut])
def list_comparables(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """The item's sales log, newest sale first."""
    get_item_or_404(db, item_id)
    return (
        db.execute(
            select(Comparable)
            .where(Comparable.item_id == item_id)
            .order_by(Comparable.sold_on.desc(), Comparable.id.desc())
        )
        .scalars()
        .all()
    )


@router.post("/api/items/{item_id}/comparables", response_model=ComparableOut, status_code=201)
def create_comparable(item_id: uuid.UUID, payload: ComparableCreate, db: Session = Depends(get_db)):
    """Log a sale you found: an eBay sold listing, an auction result, a dealer sale."""
    get_item_or_404(db, item_id)
    row = Comparable(item_id=item_id, source="manual", **_money(payload.model_dump()))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/api/comparables/{comparable_id}", response_model=ComparableOut)
def update_comparable(comparable_id: int, payload: ComparableUpdate, db: Session = Depends(get_db)):
    row = _get_or_404(db, comparable_id)
    fields = payload.model_dump(exclude_unset=True)
    for key in REQUIRED:
        if key in fields and fields[key] is None:
            raise HTTPException(status_code=422, detail=f"{key} can't be empty")
    if fields.get("currency"):
        fields["currency"] = fields["currency"].upper()
    for key, value in _money(fields).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/api/comparables/{comparable_id}", status_code=204)
def delete_comparable(comparable_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, comparable_id))
    db.commit()


@router.post("/api/items/{item_id}/comparables/numista", response_model=SalesFetchResult)
def fetch_numista_sales(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Add the auction sales Numista records for the item's issue to its sales
    log, skipping ones already there. Needs Numista's paid API plan and the
    setting that says so; spends one request (cached for a day)."""
    item = get_item_or_404(db, item_id)
    try:
        rows, issue_id = numista.fetch_sales(db, item)
    except NotApplicable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    known = set(
        db.execute(
            select(Comparable.external_id).where(
                Comparable.item_id == item_id, Comparable.external_id.is_not(None)
            )
        ).scalars()
    )
    added = 0
    for fields in rows:
        if fields["external_id"] in known:
            continue
        known.add(fields["external_id"])
        db.add(Comparable(item_id=item_id, source="numista", **fields))
        added += 1
    db.commit()
    return SalesFetchResult(
        found=len(rows), added=added, already_logged=len(rows) - added, issue_id=issue_id
    )
