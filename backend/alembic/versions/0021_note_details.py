"""v0.29.0 note details: size, printer, watermark, and demonetization.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-20
"""

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Notes (and anything not round); coins keep diameter_mm.
    op.add_column("items", sa.Column("width_mm", sa.Numeric(7, 2), nullable=True))
    op.add_column("items", sa.Column("height_mm", sa.Numeric(7, 2), nullable=True))
    op.add_column("items", sa.Column("printer", sa.String(200), nullable=True))
    op.add_column("items", sa.Column("watermark", sa.String(200), nullable=True))
    # For coins and notes alike ("valid to 1 May 1922").
    op.add_column("items", sa.Column("demonetized_on", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "demonetized_on")
    op.drop_column("items", "watermark")
    op.drop_column("items", "printer")
    op.drop_column("items", "height_mm")
    op.drop_column("items", "width_mm")
