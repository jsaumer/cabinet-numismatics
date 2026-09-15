"""Filling an item in from the Numista catalogue (roadmap Phase 5.7 C5)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import NumistaSearch, NumistaType
from app.services import numista
from app.services.pricing import NotApplicable, SourceUnavailable

router = APIRouter(prefix="/api/numista", tags=["numista"])


@router.get("/search", response_model=NumistaSearch)
def search(
    q: str = Query(min_length=2, max_length=100),
    category: Literal["coin", "banknote"] | None = None,
    db: Session = Depends(get_db),
):
    """Search the Numista catalogue by name. Needs a Numista API key."""
    try:
        return numista.search_types(db, q, category)
    except NotApplicable as exc:
        raise HTTPException(422, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/types/{type_id}", response_model=NumistaType)
def get_type(type_id: int = Path(ge=1), db: Session = Depends(get_db)):
    """A Numista type as item fields ready to fill in, its catalogue
    references, and its issues."""
    try:
        return numista.catalogue_type(db, type_id)
    except NotApplicable as exc:
        raise HTTPException(422, str(exc)) from None
    except numista.CatalogueNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None
