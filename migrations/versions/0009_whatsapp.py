"""Lot 9 — WhatsApp : fenêtre de 24 h, messages reçus, boîte d'envoi.

Revision ID: 0009_whatsapp
Revises: 0008_emails
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_whatsapp"
down_revision = "0008_emails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("dernier_message_client_le", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "whatsapp_recus",
        sa.Column("wamid", sa.String(200), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("recu_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_whatsapp_recus_conversation_id", "whatsapp_recus", ["conversation_id"])
    op.create_table(
        "whatsapp_envois",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("destinataire", sa.String(32), nullable=False),
        sa.Column("contenu", postgresql.JSONB(), nullable=False),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("essais", sa.Integer(), nullable=False),
        sa.Column("erreur", sa.String(500), nullable=True),
        sa.Column("wamid", sa.String(200), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("envoye_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_whatsapp_envois_conversation_id", "whatsapp_envois", ["conversation_id"])
    op.create_index("ix_whatsapp_envois_statut", "whatsapp_envois", ["statut"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_envois_statut", table_name="whatsapp_envois")
    op.drop_index("ix_whatsapp_envois_conversation_id", table_name="whatsapp_envois")
    op.drop_table("whatsapp_envois")
    op.drop_index("ix_whatsapp_recus_conversation_id", table_name="whatsapp_recus")
    op.drop_table("whatsapp_recus")
    op.drop_column("conversations", "dernier_message_client_le")
