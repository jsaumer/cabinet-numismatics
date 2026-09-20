"""v0.28.0 bullion stack: the metal's spot price on the day a piece was bought.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per troy ounce, in the item's own currency. `source` is server-set:
    # "manual" for a figure typed in, "auto" for one the backfill looked up.
    op.add_column("items", sa.Column("spot_at_purchase", sa.Numeric(14, 4), nullable=True))
    op.add_column("items", sa.Column("spot_at_purchase_source", sa.String(10), nullable=True))
    # A troy ounce is 31.1035 g: three decimals couldn't hold a one-ounce round.
    op.alter_column(
        "items", "weight_g", type_=sa.Numeric(9, 4), existing_type=sa.Numeric(8, 3),
        existing_nullable=True,
    )  # fmt: skip


def downgrade() -> None:
    op.alter_column(
        "items", "weight_g", type_=sa.Numeric(8, 3), existing_type=sa.Numeric(9, 4),
        existing_nullable=True,
    )  # fmt: skip
    op.drop_column("items", "spot_at_purchase_source")
    op.drop_column("items", "spot_at_purchase")
