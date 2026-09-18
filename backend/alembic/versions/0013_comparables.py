"""v0.17.0 sold-listing comps: the per-item sales log.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comparables",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sold_on", sa.Date(), nullable=False),
        sa.Column("venue", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("lot", sa.String(50), nullable=True),
        sa.Column("url", sa.String(1000), nullable=True),
        sa.Column("grade", sa.String(100), nullable=True),
        sa.Column("grade_bucket", sa.String(5), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("premium_included", sa.Boolean(), nullable=True),
        sa.Column("fees", sa.Numeric(12, 2), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(300), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("item_id", "external_id"),
    )
    op.create_index(op.f("ix_comparables_item_id"), "comparables", ["item_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_comparables_item_id"), table_name="comparables")
    op.drop_table("comparables")
