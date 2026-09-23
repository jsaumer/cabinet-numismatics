from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.permissions import permission
from app.db import get_db
from app.schemas import AccuracyReport, PricingCoverage, SourcesReport, StaleReport
from app.services import pricing_reports as reports
from app.services.app_settings import display_currency

router = APIRouter(prefix="/api/pricing", tags=["pricing reports"])


def _currency(db: Session, currency: str | None) -> str:
    return currency.upper() if currency else display_currency(db)


@router.get("/coverage", response_model=PricingCoverage)
@permission("read")
def coverage(db: Session = Depends(get_db)):
    """Owned items lacking estimates, and per source why."""
    return reports.coverage(db)


@router.get("/stale", response_model=StaleReport)
@permission("read")
def stale(days: int = Query(default=30, ge=1, le=3650), db: Session = Depends(get_db)):
    """Latest estimates per item and source that are `days` old or older, or
    were built from expired upstream data."""
    return reports.stale(db, days)


@router.get("/sources", response_model=SourcesReport)
@permission("read")
def sources(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Per-source breakdown of owned items' estimates, plus the biggest
    disagreements between sources."""
    return reports.sources(db, _currency(db, currency))


@router.get("/accuracy", response_model=AccuracyReport)
@permission("read")
def accuracy(
    currency: str | None = Query(default=None, min_length=3, max_length=3),
    db: Session = Depends(get_db),
):
    """Estimates standing at the sale date against realized prices."""
    return reports.accuracy(db, _currency(db, currency))
