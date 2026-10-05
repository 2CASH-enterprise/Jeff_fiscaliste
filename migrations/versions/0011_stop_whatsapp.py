"""Lot 11 — « STOP » sur WhatsApp : arrêt des rappels par conversation.

Revision ID: 0011_stop_whatsapp
Revises: 0010_rappels_whatsapp
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_stop_whatsapp"
down_revision = "0010_rappels_whatsapp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("rappels_whatsapp", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("conversations", "rappels_whatsapp")
