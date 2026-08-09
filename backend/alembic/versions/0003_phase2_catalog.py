"""Phase 2: item status/composition/cert/provenance fields, grades, tags, catalog refs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-09

"""

import sqlalchemy as sa

from alembic import op
from app.models.grades_seed import seed_rows

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    grades = op.create_table(
        "grades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scale", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scale", "code"),
    )
    op.bulk_insert(grades, seed_rows())

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "catalog_refs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalog", sa.String(length=50), nullable=False),
        sa.Column("ref_code", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("catalog", "ref_code"),
    )
    op.create_table(
        "item_tags",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "tag_id"),
    )
    op.create_table(
        "item_catalog_refs",
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_ref_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["catalog_ref_id"], ["catalog_refs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("item_id", "catalog_ref_id"),
    )

    op.add_column(
        "items",
        sa.Column("status", sa.String(length=10), nullable=False, server_default="owned"),
    )
    op.create_index(op.f("ix_items_status"), "items", ["status"])
    op.add_column("items", sa.Column("composition", sa.String(length=100), nullable=True))
    op.add_column("items", sa.Column("weight_g", sa.Numeric(8, 3), nullable=True))
    op.add_column("items", sa.Column("fineness", sa.Numeric(5, 4), nullable=True))
    op.add_column("items", sa.Column("grade_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_items_grade_id", "items", "grades", ["grade_id"], ["id"])
    op.add_column("items", sa.Column("cert_service", sa.String(length=50), nullable=True))
    op.add_column("items", sa.Column("cert_number", sa.String(length=50), nullable=True))
    op.add_column("items", sa.Column("acquired_from", sa.String(length=200), nullable=True))
    op.add_column("items", sa.Column("storage_location", sa.String(length=200), nullable=True))
    op.add_column("items", sa.Column("sold_date", sa.Date(), nullable=True))
    op.add_column("items", sa.Column("sold_price", sa.Numeric(12, 2), nullable=True))

    op.add_column(
        "item_photos",
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("item_photos", "position")
    for col in [
        "sold_price",
        "sold_date",
        "storage_location",
        "acquired_from",
        "cert_number",
        "cert_service",
        "grade_id",
        "fineness",
        "weight_g",
        "composition",
        "status",
    ]:
        if col == "grade_id":
            op.drop_constraint("fk_items_grade_id", "items", type_="foreignkey")
        op.drop_column("items", col)
    op.drop_table("item_catalog_refs")
    op.drop_table("item_tags")
    op.drop_table("catalog_refs")
    op.drop_table("tags")
    op.drop_table("grades")
