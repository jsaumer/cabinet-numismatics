import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PriceEstimate
from app.routers.items import get_item_or_404
from app.schemas import EstimateCreate, EstimateOut

router = APIRouter(prefix="/api/items/{item_id}/estimates", tags=["estimates"])


@router.get("", response_model=list[EstimateOut])
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


@router.post("", response_model=EstimateOut, status_code=201)
def create_estimate(item_id: uuid.UUID, payload: EstimateCreate, db: Session = Depends(get_db)):
    """Record a manually researched value. Append-only: history is never overwritten."""
    get_item_or_404(db, item_id)
    estimate = PriceEstimate(item_id=item_id, **payload.model_dump())
    db.add(estimate)
    db.commit()
    db.refresh(estimate)
    return estimate
