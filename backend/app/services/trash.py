"""The trash (v0.20.0): deleting an item moves it here with everything it
holds (photos, documents, values, sales log, history), and restoring it puts
it back as it was. Deleting from the trash (or emptying it, or the automatic
clear-out after `trash_retention_days`) is the only permanent step.

Trashed items are hidden from every ORM query by `models.item._hide_trashed`;
the functions here opt back in with `include_deleted`.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Document, Item, ItemEvent, item_documents
from app.services import app_settings
from app.services import documents as document_store
from app.services import photos as photo_store

INCLUDE = {"include_deleted": True}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def retention_days(db: Session) -> int:
    """Days an item stays in the trash before it's deleted for good; 0 = never."""
    return int(app_settings.get_setting(db, "trash_retention_days") or 0)


def purge_at(db: Session, item: Item) -> datetime | None:
    days = retention_days(db)
    if item.deleted_at is None or not days:
        return None
    return _utc(item.deleted_at) + timedelta(days=days)


def get_any(db: Session, item_id: uuid.UUID, load_related: bool = False) -> Item | None:
    """An item whether or not it's in the trash."""
    stmt = select(Item).where(Item.id == item_id).execution_options(**INCLUDE)
    if load_related:
        stmt = stmt.options(
            selectinload(Item.photos), selectinload(Item.documents), selectinload(Item.estimates)
        )
    return db.execute(stmt).scalar_one_or_none()


def trashed(db: Session) -> list[Item]:
    """Items in the trash, most recently deleted first."""
    return list(
        db.execute(
            select(Item)
            .where(Item.deleted_at.is_not(None))
            .order_by(Item.deleted_at.desc())
            .options(selectinload(Item.photos))
            .execution_options(**INCLUDE)
        ).scalars()
    )


def move_to_trash(db: Session, items: list[Item]) -> int:
    moved = 0
    stamp = now()
    for item in items:
        if item.deleted_at is None:
            item.deleted_at = stamp
            db.add(ItemEvent(item_id=item.id, action="trashed"))
            moved += 1
    db.commit()
    return moved


def restore(db: Session, items: list[Item]) -> int:
    restored = 0
    for item in items:
        if item.deleted_at is not None:
            item.deleted_at = None
            db.add(ItemEvent(item_id=item.id, action="restored"))
            restored += 1
    db.commit()
    return restored


def links(db: Session, document_id: uuid.UUID) -> int:
    """How many items, trashed ones included, a document is attached to.
    Counted on the link table itself: the ORM relationship hides trashed items."""
    return db.scalar(
        select(func.count())
        .select_from(item_documents)
        .where(item_documents.c.document_id == document_id)
    )


def delete_orphan_documents(db: Session, document_ids: list[uuid.UUID]) -> None:
    """Delete documents no item holds any more, trashed items included."""
    for document_id in document_ids:
        document = db.get(Document, document_id)
        if document is not None and links(db, document_id) == 0:
            db.delete(document)
            db.commit()
            document_store.delete_files(document_id)


def purge(db: Session, item: Item) -> None:
    """Delete an item for good: its row, photos, values, sales, history, and
    any document no other item holds."""
    document_ids = [
        row
        for row in db.execute(
            select(item_documents.c.document_id).where(item_documents.c.item_id == item.id)
        ).scalars()
    ]
    photo_store.delete_item_dir(item.id)
    db.delete(item)
    db.commit()
    delete_orphan_documents(db, document_ids)


def purge_expired(db: Session) -> int:
    """Delete items that have been in the trash longer than the retention
    setting. Run hourly by the backend's scheduler."""
    days = retention_days(db)
    if not days:
        return 0
    cutoff = now() - timedelta(days=days)
    expired = [i for i in trashed(db) if _utc(i.deleted_at) <= cutoff]
    for item in expired:
        purge(db, item)
    return len(expired)
