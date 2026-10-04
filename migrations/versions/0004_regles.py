"""Lot 4 — règles fiscales et sociales (données versionnées, sourcées, datées).

Revision ID: 0004_regles
Revises: 0003_onboarding
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_regles"
down_revision = "0003_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("juridiction_code", sa.String(2), sa.ForeignKey("juridictions.code"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("impot", sa.String(40), nullable=False),
        sa.Column("titre", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("condition", postgresql.JSONB(), nullable=False),
        sa.Column("periodicite", sa.String(20), nullable=True),
        sa.Column("echeance", sa.String(200), nullable=True),
        sa.Column("source_texte", sa.String(300), nullable=True),
        sa.Column("source_article", sa.String(100), nullable=True),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("applicable_du", sa.Date(), nullable=False),
        sa.Column("applicable_au", sa.Date(), nullable=True),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("ordre", sa.Integer(), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("juridiction_code", "code", "version", name="uq_regles_juridiction_code_version"),
    )


def downgrade() -> None:
    op.drop_table("regles")
