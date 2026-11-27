"""Tags are one per name whatever the capitals: `Silver` and `silver` are
the same tag, spelled the way it was first typed. The database folds the
case (`lower(name)`, which is also the unique index), so every lookup goes
through it here rather than comparing in Python."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Tag


def find(db: Session, name: str | None) -> Tag | None:
    """The tag `name` names, in any capitals; None when there is none."""
    name = (name or "").strip()
    if not name:
        return None
    return (
        db.execute(
            select(Tag).where(func.lower(Tag.name) == func.lower(name)).order_by(Tag.id).limit(1)
        )
        .scalars()
        .first()
    )


def resolve(db: Session, names: list[str]) -> list[Tag]:
    """Get-or-create, each tag once, in the order given. A new tag keeps the
    capitals it was typed with; an existing one keeps its own."""
    found: dict[int, Tag] = {}
    for name in names:
        name = name.strip()
        if not name:
            continue
        tag = find(db, name)
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        found.setdefault(tag.id, tag)
    return list(found.values())
