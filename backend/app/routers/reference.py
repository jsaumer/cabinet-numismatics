from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Grade, Tag, item_tags
from app.schemas import GradeOut, TagOut

router = APIRouter(prefix="/api", tags=["reference"])


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
