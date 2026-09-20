"""v0.25.0 parity fields: the PCGS population, a wish-list target and
priority, National Bank Note details, fancy-serial traits, the die axis, and
the date as struck.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-20
"""

from datetime import date

import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

COLUMNS = [
    ("pcgs_population", sa.Integer()),
    ("pcgs_pop_higher", sa.Integer()),
    ("population_as_of", sa.DateTime(timezone=True)),
    ("target_price", sa.Numeric(12, 2)),
    ("priority", sa.SmallInteger()),
    ("charter_number", sa.String(10)),
    ("bank_city", sa.String(100)),
    ("bank_state", sa.String(50)),
    ("plate_position", sa.String(20)),
    ("serial_traits", sa.String(200)),
    ("die_axis", sa.SmallInteger()),
    ("struck_calendar", sa.String(20)),
    ("struck_year", sa.Integer()),
    ("struck_era", sa.String(20)),
]

ORDER = (
    "solid", "ladder", "radar", "super_radar", "repeater", "super_repeater", "binary",
    "trinary", "low", "high", "double_quad", "date", "star",
)  # fmt: skip


def _is_date(digits: str) -> bool:
    for year, month, day in (
        (digits[4:], digits[:2], digits[2:4]),
        (digits[:4], digits[4:6], digits[6:]),
    ):
        if 1700 <= int(year) <= 2099:
            try:
                date(int(year), int(month), int(day))
            except ValueError:
                continue
            return True
    return False


def _traits(serial: str, replacement: bool) -> str | None:
    """A frozen copy of app.services.serials.traits as of this revision, so the
    backfill never changes under a later edit to the service."""
    digits = "".join(ch for ch in serial if ch.isascii() and ch.isdigit())
    n = len(digits)
    found = set()
    if n >= 4:
        distinct = len(set(digits))
        solid = distinct == 1
        steps = {int(b) - int(a) for a, b in zip(digits, digits[1:], strict=False)}
        if solid:
            found.add("solid")
        if steps in ({1}, {-1}):
            found.add("ladder")
        if not solid and digits == digits[::-1]:
            found.add("super_radar" if len(set(digits[1:-1])) == 1 else "radar")
        if not solid and n % 2 == 0:
            if digits[:2] * (n // 2) == digits:
                found.add("super_repeater")
            elif digits[: n // 2] * 2 == digits:
                found.add("repeater")
        if distinct == 2 and n >= 6:
            found.add("binary")
        if distinct == 3 and n == 8:
            found.add("trinary")
        if n >= 6 and 1 <= int(digits) <= 100:
            found.add("low")
        if n == 8:
            if int(digits) >= 99999900:
                found.add("high")
            if not solid and len(set(digits[:4])) == 1 and len(set(digits[4:])) == 1:
                found.add("double_quad")
            if _is_date(digits):
                found.add("date")
    if replacement or "*" in serial or "★" in serial:
        found.add("star")
    keys = [key for key in ORDER if key in found]
    return f",{','.join(keys)}," if keys else None


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column("items", sa.Column(name, column_type, nullable=True))

    # Backfill the traits of serial numbers already entered (trash included).
    items = sa.table(
        "items",
        sa.column("id", sa.Uuid()),
        sa.column("serial_number", sa.String()),
        sa.column("replacement_note", sa.Boolean()),
        sa.column("serial_traits", sa.String()),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(items.c.id, items.c.serial_number, items.c.replacement_note).where(
            sa.or_(items.c.serial_number.is_not(None), items.c.replacement_note.is_(True))
        )
    ).all()
    for item_id, serial, replacement in rows:
        stored = _traits(serial or "", bool(replacement))
        if stored:
            bind.execute(items.update().where(items.c.id == item_id).values(serial_traits=stored))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("items", name)
