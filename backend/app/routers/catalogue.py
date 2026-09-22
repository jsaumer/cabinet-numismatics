"""Filling an item in from the Numista catalogue (roadmap Phase 5.7 C5) or
from a PCGS cert number (Phase 5.9, v0.22.0)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.auth.permissions import permission
from app.db import get_db
from app.schemas import NumistaSearch, NumistaType, PcgsCert
from app.services import checklists, numista, pcgs
from app.services.pricing import NotApplicable, SourceUnavailable

router = APIRouter(prefix="/api/numista", tags=["numista"])
pcgs_router = APIRouter(prefix="/api/pcgs", tags=["pcgs"])


# Letters, digits, and dashes only: nothing a path segment has to encode, so
# the sign-in gate (which refuses any encoded path) never sees a real cert.
CERT_PATTERN = r"^[0-9A-Za-z-]{1,20}$"


@pcgs_router.get("/cert/{cert}", response_model=PcgsCert)
@permission("write")
def get_cert(cert: str = Path(pattern=CERT_PATTERN), db: Session = Depends(get_db)):
    """A PCGS-graded coin as item fields ready to fill in, from its cert
    number. Needs a PCGS API token; the response is cached, so pricing the
    item afterwards costs no second request."""
    try:
        return pcgs.cert_facts(db, cert)
    except NotApplicable as exc:
        raise HTTPException(422, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None


@router.get("/search", response_model=NumistaSearch)
@permission("write")
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
@permission("write")
def get_type(type_id: int = Path(ge=1), db: Session = Depends(get_db)):
    """A Numista type as item fields ready to fill in, its catalogue
    references, and its issues."""
    try:
        found = numista.catalogue_type(db, type_id)
        owned = checklists.owned_by_issue(db, catalog="numista", ref=f"N#{type_id}")
        for issue in found["issues"]:
            issue["owned"] = (issue["year"], checklists.norm(issue["mint_letter"])) in owned
        return found
    except NotApplicable as exc:
        raise HTTPException(422, str(exc)) from None
    except numista.CatalogueNotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except SourceUnavailable as exc:
        raise HTTPException(502, str(exc)) from None
