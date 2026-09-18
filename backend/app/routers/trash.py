"""The trash (v0.20.0). See services/trash.py.

Single items move in and out through `DELETE /api/items/{id}` and
`POST /api/items/{id}/restore`; these endpoints list the trash and act on
several items at once.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Item
from app.schemas import ItemIds, TrashEntry, TrashList, TrashResult
from app.services import trash

router = APIRouter(prefix="/api/trash", tags=["trash"])


def _items(db: Session, ids, *, trashed: bool | None) -> list[Item]:
    stmt = select(Item).where(Item.id.in_(ids)).execution_options(include_deleted=True)
    if trashed is True:
        stmt = stmt.where(Item.deleted_at.is_not(None))
    elif trashed is False:
        stmt = stmt.where(Item.deleted_at.is_(None))
    return list(db.execute(stmt).scalars())


@router.get("", response_model=TrashList)
def list_trash(db: Session = Depends(get_db)):
    """Items in the trash, most recently deleted first, with when each will be
    deleted for good (none when automatic emptying is off)."""
    entries = []
    for item in trash.trashed(db):
        primary = next((p for p in item.photos if p.is_primary), None)
        entries.append(
            TrashEntry(
                id=item.id,
                label=item.label,
                type=item.type,
                status=item.status,
                grade_label=item.grade_label,
                series=item.series,
                thumb_key=(primary.thumb_key or primary.file_key) if primary else None,
                deleted_at=item.deleted_at,
                purge_at=trash.purge_at(db, item),
            )
        )
    return TrashList(retention_days=trash.retention_days(db), items=entries)


@router.post("/items", response_model=TrashResult)
def move_to_trash(payload: ItemIds, db: Session = Depends(get_db)):
    """Move several items to the trash (ones already there are left as they are)."""
    return TrashResult(count=trash.move_to_trash(db, _items(db, payload.ids, trashed=False)))


@router.post("/restore", response_model=TrashResult)
def restore(payload: ItemIds, db: Session = Depends(get_db)):
    return TrashResult(count=trash.restore(db, _items(db, payload.ids, trashed=True)))


@router.post("/purge", response_model=TrashResult)
def purge(payload: ItemIds, db: Session = Depends(get_db)):
    """Delete these items from the trash for good."""
    items = _items(db, payload.ids, trashed=True)
    for item in items:
        trash.purge(db, item)
    return TrashResult(count=len(items))


@router.delete("", response_model=TrashResult)
def empty(db: Session = Depends(get_db)):
    """Delete everything in the trash for good."""
    items = trash.trashed(db)
    for item in items:
        trash.purge(db, item)
    return TrashResult(count=len(items))
