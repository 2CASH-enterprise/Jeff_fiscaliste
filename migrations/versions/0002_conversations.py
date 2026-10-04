"""Lot 2 — conversations et messages (historique commun à tous les canaux).

Revision ID: 0002_conversations
Revises: 0001_socle
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_conversations"
down_revision = "0001_socle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canal", sa.String(20), nullable=False),
        sa.Column("identifiant_externe", sa.String(100), nullable=False),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("canal", "identifiant_externe", name="uq_conversations_canal_identifiant"),
    )
    op.create_index("ix_conversations_entreprise_id", "conversations", ["entreprise_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("sens", sa.String(10), nullable=False),
        sa.Column("texte", sa.Text(), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_entreprise_id", table_name="conversations")
    op.drop_table("conversations")
