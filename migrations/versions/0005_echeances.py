"""Lot 5 — échéance calculable dans les règles.

Revision ID: 0005_echeances
Revises: 0004_regles
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_echeances"
down_revision = "0004_regles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("regles", sa.Column("echeance_calcul", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("regles", "echeance_calcul")
