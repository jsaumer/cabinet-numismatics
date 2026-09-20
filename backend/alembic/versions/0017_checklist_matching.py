"""v0.23.0 registry-style checklists: slots that know their year and mint
mark, and checklists that know which owned items fill them.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-19
"""

import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checklists", sa.Column("match_catalog", sa.String(50), nullable=True))
    op.add_column("checklists", sa.Column("match_ref", sa.String(100), nullable=True))
    op.add_column("checklists", sa.Column("match_country", sa.String(100), nullable=True))
    op.add_column("checklists", sa.Column("match_denomination", sa.String(100), nullable=True))
    op.add_column("checklist_slots", sa.Column("year", sa.Integer(), nullable=True))
    op.add_column("checklist_slots", sa.Column("mint_mark", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("checklist_slots", "mint_mark")
    op.drop_column("checklist_slots", "year")
    op.drop_column("checklists", "match_denomination")
    op.drop_column("checklists", "match_country")
    op.drop_column("checklists", "match_ref")
    op.drop_column("checklists", "match_catalog")
