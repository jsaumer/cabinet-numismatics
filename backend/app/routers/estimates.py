import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import PriceEstimate
from app.routers.items import get_item_or_404
from app.schemas import EstimateCreate, EstimateOut, RefreshResult
from app.services import pricing
from app.services.app_settings import effective_reestimate_days, get_setting

router = APIRouter(prefix="/api/items/{item_id}", tags=["estimates"])
refresh_router = APIRouter(prefix="/api/estimates", tags=["estimates"])


@refresh_router.post("/refresh-melt", response_model=RefreshResult)
def refresh_melt(db: Session = Depends(get_db)):
    """Re-run stale melt estimates now (the scheduler does this automatically
    every 12h using the cadence configured in Settings)."""
    if not get_setting(db, "melt_enabled"):
        raise HTTPException(status_code=422, detail="Melt estimation is disabled in Settings")
    return pricing.refresh_melt_estimates(db, effective_reestimate_days(db))


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
    if not get_setting(db, "melt_enabled"):
        raise HTTPException(status_code=422, detail="Melt estimation is disabled in Settings")
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
