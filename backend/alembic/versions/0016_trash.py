"""v0.20.0 safer delete: items move to a trash before they're deleted.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_items_deleted_at"), "items", ["deleted_at"])


def downgrade() -> None:
    op.drop_index(op.f("ix_items_deleted_at"), table_name="items")
    op.drop_column("items", "deleted_at")
