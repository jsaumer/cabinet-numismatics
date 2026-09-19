"""Finding items that look like one about to be added — the item form's
warning and the importer's note. A match is the same cert number (any
service), the same catalogue reference, or the same country, denomination,
year, and mint mark. Trashed items count: restoring one beats re-entering it."""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import CatalogRef, Item
from app.models.item import item_catalog_refs

LIMIT = 10


def _norm(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def find_similar(
    db: Session,
    *,
    country: str | None = None,
    denomination: str | None = None,
    year: int | None = None,
    mint_mark: str | None = None,
    cert_number: str | None = None,
    refs: list[tuple[str, str]] | None = None,
    exclude_id: uuid.UUID | None = None,
) -> list[tuple[Item, str]]:
    """Items resembling the described one, each with why; cert matches first,
    then reference matches, then identity matches; trashed items last."""
    conditions = []
    cert = _norm(cert_number)
    if cert:
        conditions.append(func.lower(func.trim(Item.cert_number)) == cert)
    wanted_refs = {(_norm(c), _norm(r)) for c, r in refs or [] if _norm(c) and _norm(r)}
    for catalog, code in wanted_refs:
        conditions.append(
            Item.id.in_(
                select(item_catalog_refs.c.item_id)
                .join(CatalogRef, CatalogRef.id == item_catalog_refs.c.catalog_ref_id)
                .where(
                    func.lower(func.trim(CatalogRef.catalog)) == catalog,
                    func.lower(func.trim(CatalogRef.ref_code)) == code,
                )
            )
        )
    identity = bool(_norm(country) and _norm(denomination) and year is not None)
    if identity:
        conditions.append(
            (func.lower(func.trim(Item.country)) == _norm(country))
            & (func.lower(func.trim(Item.denomination)) == _norm(denomination))
            & (Item.year == year)
            & (func.lower(func.trim(func.coalesce(Item.mint_mark, ""))) == _norm(mint_mark))
        )
    if not conditions:
        return []
    stmt = (
        select(Item)
        .where(or_(*conditions))
        .options(selectinload(Item.grade), selectinload(Item.catalog_refs))
        .order_by(Item.deleted_at.is_not(None), Item.created_at)
        .limit(LIMIT)
        .execution_options(include_deleted=True)
    )
    if exclude_id is not None:
        stmt = stmt.where(Item.id != exclude_id)

    def why(item: Item) -> tuple[int, str]:
        if cert and _norm(item.cert_number) == cert:
            return 0, "same cert number"
        for ref in item.catalog_refs:
            if (_norm(ref.catalog), _norm(ref.ref_code)) in wanted_refs:
                return 1, f"same {_norm(ref.catalog)} reference"
        return 2, "same country, denomination, year, and mint mark"

    found = [(item, why(item)) for item in db.execute(stmt).scalars().all()]
    found.sort(key=lambda pair: (pair[0].deleted_at is not None, pair[1][0]))
    return [(item, reason) for item, (_, reason) in found]


def describe(item: Item) -> str:
    """ "United States 25 cents 1932 "D" (MS-64, in the trash)" for a note."""
    extras = [x for x in (item.grade_label, "in the trash" if item.deleted_at else None) if x]
    return f"{item.label} ({', '.join(extras)})" if extras else item.label
