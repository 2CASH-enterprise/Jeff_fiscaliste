"""Lot 10 — rappels par WhatsApp : lien des envois avec l'entreprise, le rappel et le modèle Meta.

Revision ID: 0010_rappels_whatsapp
Revises: 0009_whatsapp
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_rappels_whatsapp"
down_revision = "0009_whatsapp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_envois", sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=True))
    op.add_column("whatsapp_envois", sa.Column("rappel_id", sa.BigInteger(), sa.ForeignKey("rappels.id"), nullable=True))
    op.add_column("whatsapp_envois", sa.Column("modele", sa.String(100), nullable=True))
    op.create_index("ix_whatsapp_envois_entreprise_id", "whatsapp_envois", ["entreprise_id"])
    op.create_index("ix_whatsapp_envois_wamid", "whatsapp_envois", ["wamid"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_envois_wamid", table_name="whatsapp_envois")
    op.drop_index("ix_whatsapp_envois_entreprise_id", table_name="whatsapp_envois")
    op.drop_column("whatsapp_envois", "modele")
    op.drop_column("whatsapp_envois", "rappel_id")
    op.drop_column("whatsapp_envois", "entreprise_id")
