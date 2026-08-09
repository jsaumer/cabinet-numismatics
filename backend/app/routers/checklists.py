from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Checklist, ChecklistSlot
from app.schemas import ChecklistCreate, ChecklistDetail, ChecklistSummary, SlotOut, SlotUpdate

router = APIRouter(prefix="/api/checklists", tags=["checklists"])


def _get_or_404(db: Session, checklist_id: int) -> Checklist:
    checklist = db.execute(
        select(Checklist).where(Checklist.id == checklist_id).options(selectinload(Checklist.slots))
    ).scalar_one_or_none()
    if checklist is None:
        raise HTTPException(status_code=404, detail="Checklist not found")
    return checklist


@router.get("", response_model=list[ChecklistSummary])
def list_checklists(db: Session = Depends(get_db)):
    rows = db.execute(select(Checklist).options(selectinload(Checklist.slots))).scalars().all()
    return [
        ChecklistSummary(
            id=c.id,
            name=c.name,
            total=len(c.slots),
            filled=sum(1 for s in c.slots if s.filled),
        )
        for c in sorted(rows, key=lambda c: c.name)
    ]


@router.post("", response_model=ChecklistDetail, status_code=201)
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
    return _get_or_404(db, checklist.id)


@router.get("/{checklist_id}", response_model=ChecklistDetail)
def get_checklist(checklist_id: int, db: Session = Depends(get_db)):
    return _get_or_404(db, checklist_id)


@router.patch("/{checklist_id}/slots/{slot_id}", response_model=SlotOut)
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
def delete_checklist(checklist_id: int, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, checklist_id))
    db.commit()
