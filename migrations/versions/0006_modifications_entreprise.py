"""Lot 6 — historique des modifications du profil des entreprises.

Revision ID: 0006_modifications_entreprise
Revises: 0005_echeances
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_modifications_entreprise"
down_revision = "0005_echeances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "modifications_entreprise",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("champ", sa.String(50), nullable=False),
        sa.Column("ancienne_valeur", postgresql.JSONB(), nullable=True),
        sa.Column("nouvelle_valeur", postgresql.JSONB(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_modifications_entreprise_entreprise_id", "modifications_entreprise", ["entreprise_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_modifications_entreprise_entreprise_id", table_name="modifications_entreprise")
    op.drop_table("modifications_entreprise")
