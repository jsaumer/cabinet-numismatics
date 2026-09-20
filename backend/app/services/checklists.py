"""Registry-style checklists and runs: which owned items fill which slot.

A generated checklist knows what fills it: a catalogue reference (every
owned item carrying Numista N#1234) or a country + denomination, and each
slot knows its year and mint mark. Matching is computed when a checklist is
read, never stored, so it follows the collection: buy the coin and the slot
fills, sell or trash it and the slot reopens. A slot ticked by hand stays
ticked either way. "Add a run" uses the same index to skip issues already
owned.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CatalogRef, Checklist, Item
from app.models.item import item_catalog_refs

MAX_SLOTS = 500


def norm(value: str | None) -> str:
    return " ".join((value or "").split()).lower()


def owned_by_issue(
    db: Session,
    *,
    catalog: str | None = None,
    ref: str | None = None,
    country: str | None = None,
    denomination: str | None = None,
) -> dict[tuple[int, str], Item]:
    """Owned items of one kind, keyed by (year, mint mark); the earliest
    entered wins a key. Trashed items are hidden by the ORM listener."""
    stmt = select(Item).where(Item.status == "owned")
    if norm(catalog) and norm(ref):
        stmt = stmt.where(
            Item.id.in_(
                select(item_catalog_refs.c.item_id)
                .join(CatalogRef, CatalogRef.id == item_catalog_refs.c.catalog_ref_id)
                .where(
                    func.lower(func.trim(CatalogRef.catalog)) == norm(catalog),
                    func.lower(func.trim(CatalogRef.ref_code)) == norm(ref),
                )
            )
        )
    elif norm(country) and norm(denomination):
        stmt = stmt.where(
            func.lower(func.trim(Item.country)) == norm(country),
            func.lower(func.trim(Item.denomination)) == norm(denomination),
        )
    else:
        return {}
    owned: dict[tuple[int, str], Item] = {}
    for item in db.execute(stmt.order_by(Item.created_at, Item.id)).scalars():
        owned.setdefault((item.year, norm(item.mint_mark)), item)
    return owned


def slot_views(db: Session, checklist: Checklist) -> list[dict]:
    """Each slot with what fills it: `filled` is a hand tick or a match."""
    owned = owned_by_issue(
        db,
        catalog=checklist.match_catalog,
        ref=checklist.match_ref,
        country=checklist.match_country,
        denomination=checklist.match_denomination,
    )
    views = []
    for slot in checklist.slots:
        match = owned.get((slot.year, norm(slot.mint_mark))) if slot.year is not None else None
        views.append(
            {
                "id": slot.id,
                "label": slot.label,
                "position": slot.position,
                "filled": slot.filled or match is not None,
                "item_id": slot.item_id,
                "year": slot.year,
                "mint_mark": slot.mint_mark,
                "matched_item_id": match.id if match else None,
                "matched_label": match.label if match else None,
            }
        )
    return views


def label_for(year: int, mint_mark: str | None) -> str:
    mint = " ".join((mint_mark or "").split())
    return f"{year}-{mint}" if mint else str(year)


def slots_from_issues(issues: list[dict]) -> list[tuple[str, int, str | None]]:
    """(label, year, mint mark) per distinct dated issue, in date order."""
    seen: dict[tuple[int, str], tuple[str, int, str | None]] = {}
    for issue in issues:
        year = issue.get("year")
        if not isinstance(year, int):
            continue
        mint = " ".join((issue.get("mint_letter") or "").split()) or None
        seen.setdefault((year, norm(mint)), (label_for(year, mint), year, mint))
    return [seen[key] for key in sorted(seen)]


def slots_from_range(
    year_from: int, year_to: int, mint_marks: list[str], skip: list[str]
) -> list[tuple[str, int, str | None]]:
    """Every year × mint mark, less the labels in `skip` ("1933", "1965-D")."""
    mints = list(dict.fromkeys(" ".join(m.split()) for m in (mint_marks or [""])))
    skipped = {norm(label) for label in skip}
    slots = []
    for year in range(year_from, year_to + 1):
        for mint in mints:
            label = label_for(year, mint)
            if norm(label) not in skipped:
                slots.append((label, year, mint or None))
    return slots
