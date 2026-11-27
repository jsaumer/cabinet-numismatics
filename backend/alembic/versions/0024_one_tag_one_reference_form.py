"""One tag per name whatever the capitals, and one written form for a
Numista reference.

Tags: `Silver` and `silver` were two tags that the list's filter merged and
the dashboard kept apart. Tags that differ only by case become the one
entered first (its spelling stays, every item keeps the tag), and a unique
index on `lower(name)` keeps it so.

Catalog references: a Numista type number was stored as typed (`1234`,
`N#1234`, `N# 1234`), so pricing found it and the duplicate check,
checklists, and "Add a run" did not. Each becomes `N#<digits>`, merged into
the row that already has that form when there is one. A Numista reference
that isn't a number is left as it is.

The reference rule below is a frozen copy of `app/services/refs.py` as of
this revision: never import the service into a migration.

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-26
"""

import re

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

tags = sa.table("tags", sa.column("id", sa.Integer), sa.column("name", sa.String))
item_tags = sa.table("item_tags", sa.column("item_id", sa.Uuid), sa.column("tag_id", sa.Integer))
catalog_refs = sa.table(
    "catalog_refs",
    sa.column("id", sa.Integer),
    sa.column("catalog", sa.String),
    sa.column("ref_code", sa.String),
)
item_catalog_refs = sa.table(
    "item_catalog_refs", sa.column("item_id", sa.Uuid), sa.column("catalog_ref_id", sa.Integer)
)

_NUMISTA_REF = re.compile(r"^\s*(?:n\s*[#-]?\s*)?0*([1-9]\d{0,8})\s*$", re.IGNORECASE)


def _numista_ref(code):
    match = _NUMISTA_REF.match(code or "")
    return f"N#{match.group(1)}" if match else None


def _merge(bind, links, column, gone: int, kept: int) -> None:
    """Point every link at `kept` instead of `gone`. An item linked to both
    would collide on the link table's primary key, so that link goes first."""
    both = sa.select(links.c.item_id).where(column == kept)
    bind.execute(links.delete().where(column == gone, links.c.item_id.in_(both)))
    bind.execute(links.update().where(column == gone).values({column.name: kept}))


def upgrade() -> None:
    bind = op.get_bind()

    # The database folds the case, as the index and every lookup will.
    kept_tags: dict[str, int] = {}
    folded = sa.func.lower(tags.c.name)
    for tag_id, name in bind.execute(sa.select(tags.c.id, folded).order_by(tags.c.id)).all():
        kept = kept_tags.setdefault(name, tag_id)
        if kept != tag_id:
            _merge(bind, item_tags, item_tags.c.tag_id, tag_id, kept)
            bind.execute(tags.delete().where(tags.c.id == tag_id))
    op.create_index("uq_tags_name_lower", "tags", [sa.text("lower(name)")], unique=True)

    numista = sa.func.lower(sa.func.trim(catalog_refs.c.catalog)) == "numista"
    rows = bind.execute(
        sa.select(catalog_refs.c.id, catalog_refs.c.catalog, catalog_refs.c.ref_code)
        .where(numista)
        .order_by(catalog_refs.c.id)
    ).all()
    # Rows already in the form are the ones the others merge into.
    kept_refs = {
        code: ref_id
        for ref_id, catalog, code in rows
        if (catalog, code) == ("numista", _numista_ref(code))
    }
    for ref_id, _, code in rows:
        form = _numista_ref(code)
        if form is None or kept_refs.get(form) == ref_id:
            continue
        if form in kept_refs:
            link = item_catalog_refs.c.catalog_ref_id
            _merge(bind, item_catalog_refs, link, ref_id, kept_refs[form])
            bind.execute(catalog_refs.delete().where(catalog_refs.c.id == ref_id))
        else:
            bind.execute(
                catalog_refs.update()
                .where(catalog_refs.c.id == ref_id)
                .values(catalog="numista", ref_code=form)
            )
            kept_refs[form] = ref_id


def downgrade() -> None:
    # Merged tags and rewritten references stay as they are: nothing recorded
    # which spelling each item had.
    op.drop_index("uq_tags_name_lower", table_name="tags")
