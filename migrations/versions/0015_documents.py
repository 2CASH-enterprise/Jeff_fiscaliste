"""Lot 15 — documents du coffre fiscal (fichiers sur le volume jeff_documents).

Revision ID: 0015_documents
Revises: 0014_preferences_rappels
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_documents"
down_revision = "0014_preferences_rappels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=False),
        sa.Column("type_document", sa.String(20), nullable=False),
        sa.Column("mois", sa.Date(), nullable=False),
        sa.Column("nom", sa.String(150), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("taille", sa.Integer(), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=False),
        sa.Column("session_espace_id", sa.BigInteger(), sa.ForeignKey("sessions_espace.id"), nullable=True),
        sa.Column("depose_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("type_document IN ('facture', 'paie', 'declaration', 'attestation', 'autre')", name="ck_documents_type"),
        sa.CheckConstraint("format IN ('pdf', 'jpeg', 'png')", name="ck_documents_format"),
        sa.CheckConstraint("taille > 0", name="ck_documents_taille"),
        sa.CheckConstraint("extract(day from mois) = 1", name="ck_documents_mois"),
    )
    op.create_index("ix_documents_entreprise_id", "documents", ["entreprise_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_entreprise_id", table_name="documents")
    op.drop_table("documents")
