from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.auth.permissions import permission
from app.db import get_db
from app.models import Checklist, ChecklistSlot
from app.schemas import (
    ChecklistCreate,
    ChecklistDetail,
    ChecklistGenerate,
    ChecklistSummary,
    SlotOut,
    SlotUpdate,
)
from app.services import checklists, numista
from app.services.pricing import NotApplicable, SourceUnavailable

router = APIRouter(prefix="/api/checklists", tags=["checklists"])


def _get_or_404(db: Session, checklist_id: int) -> Checklist:
    checklist = db.execute(
        select(Checklist).where(Checklist.id == checklist_id).options(selectinload(Checklist.slots))
    ).scalar_one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return checklist


def _detail(db: Session, checklist: Checklist) -> ChecklistDetail:
    slots = checklists.slot_views(db, checklist)
    return ChecklistDetail(
        id=checklist.id,
        name=checklist.name,
        match_catalog=checklist.match_catalog,
        match_ref=checklist.match_ref,
        match_country=checklist.match_country,
        match_denomination=checklist.match_denomination,
        total=len(slots),
        filled=sum(1 for s in slots if s["filled"]),
        slots=slots,
    )


@router.get("", response_model=list[ChecklistSummary])
@permission("read")
def list_checklists(db: Session = Depends(get_db)):
    rows = db.execute(select(Checklist).options(selectinload(Checklist.slots))).scalars().all()
    out = []
    for c in sorted(rows, key=lambda c: c.name):
        slots = checklists.slot_views(db, c)
        out.append(
            ChecklistSummary(
                id=c.id,
                name=c.name,
                total=len(slots),
                filled=sum(1 for s in slots if s["filled"]),
                generated=bool(c.match_ref or c.match_country),
            )
        )
    return out


@router.post("", response_model=ChecklistDetail, status_code=201)
@permission("write")
def create_checklist(payload: ChecklistCreate, db: Session = Depends(get_db)):
    checklist = Checklist(name=payload.name.strip())
    checklist.slots = [
        ChecklistSlot(label=label.strip(), position=i)
        for i, label in enumerate(payload.slots)
        if label.strip()
    ]
    if not checklist.slots:
        raise HTTPException(status_code=422, detail="At least one non-empty slot is required")
    db.add(checklist)
    db.commit()
    return _detail(db, _get_or_404(db, checklist.id))


@router.post("/generate", response_model=ChecklistDetail, status_code=201)
@permission("write")
def generate_checklist(payload: ChecklistGenerate, db: Session = Depends(get_db)):
    """A checklist whose slots fill themselves: one per issue of a Numista
    type, or one per year and mint mark of a range."""
    checklist = Checklist()
    if payload.source == "numista":
        if payload.type_id is None:
            raise HTTPException(422, "type_id is required to generate from a Numista type")
        try:
            found = numista.catalogue_type(db, payload.type_id)
        except NotApplicable as exc:
            raise HTTPException(422, str(exc)) from None
        except numista.CatalogueNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except SourceUnavailable as exc:
            raise HTTPException(502, str(exc)) from None
        slots = checklists.slots_from_issues(found["issues"])
        if not slots:
            raise HTTPException(422, f"Numista lists no dated issues for {found['title']}")
        name = payload.name or found["title"]
        checklist.match_catalog, checklist.match_ref = "numista", f"N#{payload.type_id}"
    else:
        if not (payload.country and payload.denomination) or None in (
            payload.year_from,
            payload.year_to,
        ):
            raise HTTPException(
                422, "A range needs a country, a denomination, and a first and last year"
            )
        if payload.year_to < payload.year_from:
            raise HTTPException(422, "The last year is before the first")
        slots = checklists.slots_from_range(
            payload.year_from, payload.year_to, payload.mint_marks, payload.skip
        )
        if not slots:
            raise HTTPException(422, "That range leaves no slots")
        name = payload.name or (
            f"{payload.country.strip()} {payload.denomination.strip()} "
            f"{payload.year_from}–{payload.year_to}"
        )
        checklist.match_country = payload.country.strip()
        checklist.match_denomination = payload.denomination.strip()
    if len(slots) > checklists.MAX_SLOTS:
        raise HTTPException(422, f"That makes {len(slots)} slots; the limit is 500")
    checklist.name = name.strip()[:100]
    checklist.slots = [
        ChecklistSlot(label=label, position=i, year=year, mint_mark=mint)
        for i, (label, year, mint) in enumerate(slots)
    ]
    db.add(checklist)
    db.commit()
    return _detail(db, _get_or_404(db, checklist.id))


@router.get("/{checklist_id}", response_model=ChecklistDetail)
@permission("read")
def get_checklist(checklist_id: int, db: Session = Depends(get_db)):
    return _detail(db, _get_or_404(db, checklist_id))


@router.patch("/{checklist_id}/slots/{slot_id}", response_model=SlotOut)
@permission("write")
def update_slot(
    checklist_id: int, slot_id: int, payload: SlotUpdate, db: Session = Depends(get_db)
):
    slot = db.get(ChecklistSlot, slot_id)
    if slot is None or slot.checklist_id != checklist_id:
        raise HTTPException(status_code=404, detail="Slot not found")
    if payload.filled is not None:
        slot.filled = payload.filled
        if not payload.filled:
            slot.item_id = None
    if payload.item_id is not None:
        slot.item_id = payload.item_id
        slot.filled = True
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/{checklist_id}", status_code=204)
@permission("write")
def delete_checklist(checklist_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, checklist_id))
    db.commit()
