"""v0.27.1 undated pieces: a year is optional, with an ND flag beside it.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

items = sa.table("items", sa.column("year", sa.Integer()), sa.column("year_nd", sa.Boolean()))


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("year_nd", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("items", "year", existing_type=sa.Integer(), nullable=True)
    # There is no year 0: it is what gets typed when the field is required and
    # the piece carries no date.
    op.execute(items.update().where(items.c.year == 0).values(year=None, year_nd=True))


def downgrade() -> None:
    op.execute(items.update().where(items.c.year.is_(None)).values(year=0))
    op.alter_column("items", "year", existing_type=sa.Integer(), nullable=False)
    op.drop_column("items", "year_nd")
