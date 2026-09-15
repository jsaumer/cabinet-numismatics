"""Pricing program M4: estimate provenance.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-14
"""

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_estimates", sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_estimates", "details")
