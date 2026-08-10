"""Pricing program M2: cached responses from external price sources.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-10

"""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_cache",
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("cache_key", sa.String(length=200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("source", "cache_key"),
    )


def downgrade() -> None:
    op.drop_table("source_cache")
