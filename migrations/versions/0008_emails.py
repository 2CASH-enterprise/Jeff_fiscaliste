"""Lot 8 — adresse email des entreprises et boîte d'envoi des emails.

Revision ID: 0008_emails
Revises: 0007_rappels
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_emails"
down_revision = "0007_rappels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entreprises", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("entreprises", sa.Column("email_confirme_le", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "emails",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=True),
        sa.Column("rappel_id", sa.BigInteger(), sa.ForeignKey("rappels.id"), nullable=True),
        sa.Column("destinataire", sa.String(254), nullable=False),
        sa.Column("objet", sa.String(200), nullable=False),
        sa.Column("texte", sa.Text(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("essais", sa.Integer(), nullable=False),
        sa.Column("erreur", sa.String(500), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("envoye_le", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_emails_entreprise_id", "emails", ["entreprise_id"])
    op.create_index("ix_emails_statut", "emails", ["statut"])


def downgrade() -> None:
    op.drop_index("ix_emails_statut", table_name="emails")
    op.drop_index("ix_emails_entreprise_id", table_name="emails")
    op.drop_table("emails")
    op.drop_column("entreprises", "email_confirme_le")
    op.drop_column("entreprises", "email")
