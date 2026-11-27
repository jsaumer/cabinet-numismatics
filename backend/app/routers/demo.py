"""The demo collection: seventeen pieces to look at before entering real
ones. See services/demo.py.

Loading is `write` because it does nothing a write token couldn't do one
call at a time (create pieces, record values, import photos by URL), and it
only ever runs against an empty collection. Removing is `admin` and `fresh`
like every other way of deleting a piece for good.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.permissions import permission
from app.db import get_db
from app.schemas import DemoRemoved, DemoStatus
from app.services import demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("", response_model=DemoStatus)
@permission("read")
def demo_status(db: Session = Depends(get_db)):
    """How many demo pieces there are (the trash included) and how far the
    photo fetch has got."""
    return demo.status(db)


@router.post("", response_model=DemoStatus, status_code=201)
@permission("write")
def load_demo(
    photos: bool = Query(default=True, description="Fetch the photos from Wikimedia Commons"),
    db: Session = Depends(get_db),
):
    """Load the demo collection into an empty collection. The pieces and
    their values are there when this answers; the photos follow in the
    background, and `GET /api/demo` says how far they have got."""
    try:
        return demo.load(db, photos=photos)
    except demo.Refused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.delete("", response_model=DemoRemoved)
@permission("admin", fresh=True)
def remove_demo(db: Session = Depends(get_db)):
    """Delete every demo piece for good, with its photos and values. Pieces
    entered by hand or imported are never touched."""
    try:
        return {"removed": demo.remove(db)}
    except demo.Refused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
