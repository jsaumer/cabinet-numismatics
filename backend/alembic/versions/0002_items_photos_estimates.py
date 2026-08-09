"""Phase 1: items, item_photos, price_estimates.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=10), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("denomination", sa.String(length=100), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("mint_mark", sa.String(length=20), nullable=True),
        sa.Column("series", sa.String(length=200), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=True),
        sa.Column("acquisition_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_items_type"), "items", ["type"])
    op.create_index(op.f("ix_items_country"), "items", ["country"])
    op.create_index(op.f("ix_items_year"), "items", ["year"])

    op.create_table(
        "item_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("file_key", sa.String(length=300), nullable=False),
        sa.Column("thumb_key", sa.String(length=300), nullable=True),
        sa.Column("angle", sa.String(length=10), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_item_photos_item_id"), "item_photos", ["item_id"])

    op.create_table(
        "price_estimates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("estimated_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_price_estimates_item_id"), "price_estimates", ["item_id"])


def downgrade() -> None:
    op.drop_table("price_estimates")
    op.drop_table("item_photos")
    op.drop_table("items")
