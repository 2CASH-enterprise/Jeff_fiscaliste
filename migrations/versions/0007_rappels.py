"""Lot 7 — rappels d'échéances.

Revision ID: 0007_rappels
Revises: 0006_modifications_entreprise
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_rappels"
down_revision = "0006_modifications_entreprise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rappels",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=False),
        sa.Column("regle_id", sa.Uuid(), sa.ForeignKey("regles.id"), nullable=False),
        sa.Column("regle_code", sa.String(60), nullable=False),
        sa.Column("periode", sa.String(50), nullable=False),
        sa.Column("date_limite", sa.Date(), nullable=False),
        sa.Column("palier", sa.Integer(), nullable=False),
        sa.Column("date_prevue", sa.Date(), nullable=False),
        sa.Column("canal", sa.String(20), nullable=False),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("envoye_le", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "entreprise_id", "regle_code", "date_limite", "palier", name="uq_rappels_entreprise_regle_date_palier"
        ),
    )
    op.create_index("ix_rappels_entreprise_id", "rappels", ["entreprise_id"])


def downgrade() -> None:
    op.drop_index("ix_rappels_entreprise_id", table_name="rappels")
    op.drop_table("rappels")
