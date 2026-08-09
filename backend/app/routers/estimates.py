import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PriceEstimate
from app.routers.items import get_item_or_404
from app.schemas import EstimateCreate, EstimateOut
from app.services import pricing

router = APIRouter(prefix="/api/items/{item_id}", tags=["estimates"])


@router.get("/estimates", response_model=list[EstimateOut])
def list_estimates(item_id: uuid.UUID, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    return (
        db.execute(
            select(PriceEstimate)
            .where(PriceEstimate.item_id == item_id)
            .order_by(PriceEstimate.fetched_at.desc())
        )
        .scalars()
        .all()
    )


@router.post("/estimates", response_model=EstimateOut, status_code=201)
def create_estimate(item_id: uuid.UUID, payload: EstimateCreate, db: Session = Depends(get_db)):
    """Record a manually researched value. Append-only: history is never overwritten."""
    get_item_or_404(db, item_id)
    estimate = PriceEstimate(item_id=item_id, **payload.model_dump())
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return estimate


@router.post("/estimate", response_model=EstimateOut, status_code=201)
def auto_estimate(item_id: uuid.UUID, db: Session = Depends(get_db)):
    """Produce an automatic estimate. Phase 3 ships the melt-value adapter;
    further sources join the registry later."""
    item = get_item_or_404(db, item_id)
    try:
        result = pricing.melt_estimate(db, item)
    except pricing.NotApplicable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except pricing.SpotUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    estimate = PriceEstimate(
        item_id=item_id,
        source=result.source,
        estimated_value=result.estimated_value,
        currency=result.currency,
        confidence=result.confidence,
        sample_size=result.sample_size,
    )
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return estimate
