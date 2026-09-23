"""v0.32.0 share links: read-only public links to the collection, a set, or
a checklist. Only each token's SHA-256 is stored.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-23
"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "share_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(10), nullable=False),
        # Deleting the set or checklist deletes its links; the collection has neither.
        sa.Column(
            "set_id", sa.Integer(), sa.ForeignKey("sets.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "checklist_id",
            sa.Integer(),
            sa.ForeignKey("checklists.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("show_photos", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_grades", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_tags", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("show_notes", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("show_values", sa.Boolean(), nullable=False, server_default=sa.false()),
        # The cert number alone: a lookup key into auction archives (v0.32.0 review).
        sa.Column("show_certs", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(op.f("ix_share_links_set_id"), "share_links", ["set_id"])
    op.create_index(op.f("ix_share_links_checklist_id"), "share_links", ["checklist_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_share_links_checklist_id"), table_name="share_links")
    op.drop_index(op.f("ix_share_links_set_id"), table_name="share_links")
    op.drop_table("share_links")
