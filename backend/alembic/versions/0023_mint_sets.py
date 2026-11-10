"""v0.37.0 proof and mint sets: piece count, packaging, and the stack choice.

The new item type `mint_set` needs no change here: `items.type` is a
non-native enum of length 10 with no database constraint.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-25
"""

import sqlalchemy as sa

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every piece in a set: coins, any banknote, any mint token or medal.
    op.add_column("items", sa.Column("piece_count", sa.SmallInteger(), nullable=True))
    # sealed | complete | incomplete; empty means not recorded.
    op.add_column("items", sa.Column("packaging", sa.String(12), nullable=True))
    op.add_column(
        "items", sa.Column("has_box", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "items", sa.Column("has_coa", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    # A set's precious metal counts in the stack only when the owner says so.
    op.add_column(
        "items",
        sa.Column("count_in_stack", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("items", "count_in_stack")
    op.drop_column("items", "has_coa")
    op.drop_column("items", "has_box")
    op.drop_column("items", "packaging")
    op.drop_column("items", "piece_count")
