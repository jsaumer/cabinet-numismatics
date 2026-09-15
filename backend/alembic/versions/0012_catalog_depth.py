"""v0.14.0 catalog depth: grading depth, physical and banknote fields, costs.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-15
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

# PMG's lowest grades, missing from the 0003 seed. A fresh database already gets
# them from the seed list, so insert only what isn't there.
PMG_LOW = [("1", "Poor", 1), ("2", "Fair", 2), ("3", "About Good", 3)]


def _columns() -> list[sa.Column]:
    return [
        sa.Column("strike", sa.String(10), nullable=False, server_default="business"),
        sa.Column("grade_plus", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("grade_star", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("designations", sa.JSON(), nullable=True),
        sa.Column("grade_details", sa.String(100), nullable=True),
        sa.Column("cac_sticker", sa.String(10), nullable=True),
        sa.Column("diameter_mm", sa.Numeric(6, 2), nullable=True),
        sa.Column("thickness_mm", sa.Numeric(5, 2), nullable=True),
        sa.Column("edge", sa.String(100), nullable=True),
        sa.Column("shape", sa.String(50), nullable=True),
        sa.Column("mintage", sa.BigInteger(), nullable=True),
        sa.Column("serial_number", sa.String(50), nullable=True),
        sa.Column("prefix_block", sa.String(50), nullable=True),
        sa.Column("signatures", sa.String(200), nullable=True),
        sa.Column("issuer", sa.String(200), nullable=True),
        sa.Column("replacement_note", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("acquisition_fees", sa.Numeric(12, 2), nullable=True),
        sa.Column("sold_fees", sa.Numeric(12, 2), nullable=True),
        sa.Column("sold_to", sa.String(200), nullable=True),
    ]


def upgrade() -> None:
    for column in _columns():
        op.add_column("items", column)
    insert = sa.text(
        "INSERT INTO grades (scale, code, label, rank) "
        "SELECT 'pmg', :code, :label, :rank "
        "WHERE NOT EXISTS (SELECT 1 FROM grades WHERE scale = 'pmg' AND code = :code)"
    )
    for code, label, rank in PMG_LOW:
        op.execute(insert.bindparams(code=code, label=label, rank=rank))


def downgrade() -> None:
    # The PMG 1–3 grade rows stay: fresh databases got them from the seed, and
    # an unused reference row is harmless.
    for column in reversed(_columns()):
        op.drop_column("items", column.name)
