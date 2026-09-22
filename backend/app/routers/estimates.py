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


@refresh_router.post("/refresh", response_model=RefreshResult)
def refresh(source: str, db: Session = Depends(get_db)):
    """Re-run one source's stale estimates now (the scheduler does this
    automatically every 12h using the cadence configured in Settings). Only
    `melt` can be refreshed by hand for now."""
    if source != "melt":
        raise HTTPException(status_code=422, detail="Only melt can be refreshed by hand for now.")
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
    item = get_item_or_404(db, item_id)
    note = (payload.note or "").strip()
    estimate = PriceEstimate(
        item_id=item_id,
        **payload.model_dump(exclude={"note"}),
        details={"note": note} if note else None,
    )
    pricing.add_estimate(db, item, estimate)
    db.commit()
    db.refresh(estimate)
    return estimate


@router.delete("/estimates/{estimate_id}", status_code=204)
def delete_estimate(item_id: uuid.UUID, estimate_id: uuid.UUID, db: Session = Depends(get_db)):
    """Remove a value that was typed in. What a price source said stays: that
    history is the record the reports and the provenance are built on."""
    get_item_or_404(db, item_id)
    estimate = db.get(PriceEstimate, estimate_id)
    if estimate is None or estimate.item_id != item_id:
        raise HTTPException(status_code=404, detail="Estimate not found")
    if pricing.source_key(estimate.source) in pricing.ADAPTER_NAMES:
        raise HTTPException(
            status_code=409,
            detail="Only a value you typed in can be deleted; a price source's values are kept",
        )
    db.delete(estimate)
    db.commit()


@router.post("/estimates/auto", response_model=EstimateOut, status_code=201)
def auto_estimate(item_id: uuid.UUID, source: str = "melt", db: Session = Depends(get_db)):
    """Produce an automatic estimate from one price source: `melt` (default),
    `numista`, or `pcgs`. The outcome is recorded for the coverage report."""
    item = get_item_or_404(db, item_id)
    if pricing.get_adapter(source) is None:
        raise HTTPException(status_code=422, detail=f"Unknown price source {source!r}")
    if not get_setting(db, f"{source}_enabled"):
        raise HTTPException(
            status_code=422, detail=f"{source.capitalize()} estimation is disabled in Settings"
        )
    try:
        result = pricing.run_adapter(db, item, source)
    except pricing.NotApplicable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except pricing.SourceUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    estimate = pricing.add_estimate(db, item, pricing.estimate_row(item_id, result))
    db.commit()
    db.refresh(estimate)
    return estimate
