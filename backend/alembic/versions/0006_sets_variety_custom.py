"""Phase 5B: sets/lots, variety, custom fields.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-09

"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("items", sa.Column("variety", sa.String(length=200), nullable=True))
    op.add_column("items", sa.Column("set_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_items_set_id", "items", "sets", ["set_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("items", sa.Column("custom_fields", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "custom_fields")
    op.drop_constraint("fk_items_set_id", "items", type_="foreignkey")
    op.drop_column("items", "set_id")
    op.drop_column("items", "variety")
    op.drop_table("sets")
