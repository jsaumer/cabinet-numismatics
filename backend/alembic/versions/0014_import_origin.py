"""v0.18.0 imports: where an imported item came from.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("import_source", sa.String(30), nullable=True))
    op.add_column("items", sa.Column("import_key", sa.String(300), nullable=True))
    op.create_unique_constraint("uq_items_import_origin", "items", ["import_source", "import_key"])


def downgrade() -> None:
    op.drop_constraint("uq_items_import_origin", "items", type_="unique")
    op.drop_column("items", "import_key")
    op.drop_column("items", "import_source")
