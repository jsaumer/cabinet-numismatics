"""Phase 3: spot price cache for melt-value estimation.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-09

"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spot_prices",
        sa.Column("metal", sa.String(length=20), nullable=False),
        sa.Column("price_per_gram", sa.Numeric(12, 6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("metal"),
    )


def downgrade() -> None:
    op.drop_table("spot_prices")
