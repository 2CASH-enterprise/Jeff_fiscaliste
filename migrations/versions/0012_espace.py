"""Lot 12 — coffre fiscal : demandes de code de connexion et sessions.

Revision ID: 0012_espace
Revises: 0011_stop_whatsapp
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_espace"
down_revision = "0011_stop_whatsapp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demandes_connexion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("empreinte", sa.String(64), nullable=True),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("essais", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("renvois", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("statut", sa.String(20), server_default="en_cours", nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("statut IN ('en_cours', 'utilisee', 'abandonnee')", name="ck_demandes_connexion_statut"),
    )
    op.create_index("ix_demandes_connexion_email", "demandes_connexion", ["email"])

    op.create_table(
        "sessions_espace",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("empreinte_jeton", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("entreprise_id", sa.Uuid(), sa.ForeignKey("entreprises.id"), nullable=True),
        sa.Column("user_agent", sa.String(200), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("derniere_activite_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fermee_le", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("empreinte_jeton", name="uq_sessions_espace_empreinte_jeton"),
    )
    op.create_index("ix_sessions_espace_email", "sessions_espace", ["email"])


def downgrade() -> None:
    op.drop_index("ix_sessions_espace_email", table_name="sessions_espace")
    op.drop_table("sessions_espace")
    op.drop_index("ix_demandes_connexion_email", table_name="demandes_connexion")
    op.drop_table("demandes_connexion")
