"""v0.19.0 documents: attached files, shareable between items.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("kind", sa.String(30), nullable=False, server_default="other"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pages", sa.Integer(), nullable=True),
        sa.Column("file_key", sa.String(300), nullable=False),
        sa.Column("thumb_key", sa.String(300), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"])
    op.create_table(
        "item_documents",
        sa.Column(
            "item_id", sa.Uuid(), sa.ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "document_id",
            sa.Uuid(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("item_documents")
    op.drop_index(op.f("ix_documents_sha256"), table_name="documents")
    op.drop_table("documents")
