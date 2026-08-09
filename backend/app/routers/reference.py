from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Grade, Item, ItemSet, Tag, item_tags
from app.schemas import GradeOut, SetCreate, SetOut, SetWithCount, TagOut

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
        select(Tag.name, func.count(item_tags.c.item_id))
        .outerjoin(item_tags, Tag.id == item_tags.c.tag_id)
        .group_by(Tag.name)
        .order_by(Tag.name)
    ).all()
    return [TagOut(name=name, count=count) for name, count in rows]
