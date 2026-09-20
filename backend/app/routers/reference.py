from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Grade, Item, ItemSet, Tag, item_tags
from app.schemas import (
    CalendarReference,
    ConvertedDate,
    GradeOut,
    SerialTraitOut,
    SetCreate,
    SetOut,
    SetWithCount,
    TagOut,
)
from app.services import calendars, serials

router = APIRouter(prefix="/api", tags=["reference"])


@router.get("/sets", response_model=list[SetWithCount])
def list_sets(db: Session = Depends(get_db)):
    rows = db.execute(
        select(ItemSet, func.count(Item.id))
        .outerjoin(Item, Item.set_id == ItemSet.id)
        .group_by(ItemSet.id)
        .order_by(ItemSet.name)
    ).all()
    return [
        SetWithCount(id=s.id, name=s.name, notes=s.notes, item_count=count) for s, count in rows
    ]


@router.post("/sets", response_model=SetOut, status_code=201)
def create_set(payload: SetCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if db.execute(select(ItemSet).where(ItemSet.name == name)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Set {name!r} already exists")
    row = ItemSet(name=name, notes=payload.notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/sets/{set_id}", response_model=SetOut)
def update_set(set_id: int, payload: SetCreate, db: Session = Depends(get_db)):
    row = db.get(ItemSet, set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Set not found")
    row.name = payload.name.strip()
    row.notes = payload.notes
    db.commit()
    db.refresh(row)
    return row


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: int, db: Session = Depends(get_db)):
    row = db.get(ItemSet, set_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Set not found")
    db.delete(row)  # items keep existing; their set_id becomes NULL
    db.commit()


@router.get("/grades", response_model=list[GradeOut])
def list_grades(
    scale: str | None = Query(default=None, max_length=20), db: Session = Depends(get_db)
):
    stmt = select(Grade).order_by(Grade.scale, Grade.rank)
    if scale:
        stmt = stmt.where(Grade.scale == scale.lower())
    return db.execute(stmt).scalars().all()


@router.get("/tags", response_model=list[TagOut])
def list_tags(db: Session = Depends(get_db)):
    rows = db.execute(
        # Counted through the link table, which the trash filter can't see, so
        # trashed items are left out here explicitly.
        select(Tag.name, func.count(Item.id))
        .outerjoin(item_tags, Tag.id == item_tags.c.tag_id)
        .outerjoin(Item, and_(Item.id == item_tags.c.item_id, Item.deleted_at.is_(None)))
        .group_by(Tag.name)
        .order_by(Tag.name)
    ).all()
    return [TagOut(name=name, count=count) for name, count in rows]


@router.get("/reference/serial-traits", response_model=list[SerialTraitOut])
def serial_traits():
    """The fancy-serial traits an item's `serial_traits` can hold, in order."""
    return [
        {"key": key, "label": label, "description": description}
        for key, (label, description) in serials.TRAITS.items()
    ]


@router.get("/reference/calendars", response_model=CalendarReference)
def list_calendars():
    """The calendars a date as struck can be in, and the Japanese eras."""
    return {
        "calendars": [{"key": k, "label": label} for k, label in calendars.CALENDARS.items()],
        "eras": [
            {"key": k, "label": calendars.ERA_LABELS[k], "offset": offset}
            for k, offset in calendars.ERAS.items()
        ],
    }


@router.get("/reference/convert-date", response_model=ConvertedDate)
def convert_date(
    calendar: str = Query(max_length=20),
    year: int = Query(ge=1, le=9999),
    era: str | None = Query(default=None, max_length=20),
):
    """The Gregorian year a struck year mostly falls in."""
    calendar, era = calendar.strip().lower(), (era or "").strip().lower() or None
    try:
        gregorian = calendars.to_gregorian(calendar, year, era)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"calendar": calendar, "year": year, "era": era, "gregorian_year": gregorian}
