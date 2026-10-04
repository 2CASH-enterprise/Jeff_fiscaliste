"""Lot 3 — profil déclaré des entreprises et parcours (onboarding).

Revision ID: 0003_onboarding
Revises: 0002_conversations
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_onboarding"
down_revision = "0002_conversations"
branch_labels = None
depends_on = None

COLONNES_ENTREPRISE = (
    ("forme_juridique", sa.String(30)),
    ("secteur", sa.String(30)),
    ("chiffre_affaires_annuel", sa.BigInteger()),
    ("centre_impots", sa.String(100)),
    ("regime_declare", sa.String(20)),
    ("assujetti_tva_declare", sa.Boolean()),
    ("nombre_salaries", sa.Integer()),
    ("numero_employeur_cnps", sa.String(30)),
)


def upgrade() -> None:
    for nom, type_ in COLONNES_ENTREPRISE:
        op.add_column("entreprises", sa.Column(nom, type_, nullable=True))

    op.create_table(
        "parcours",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("etape", sa.String(50), nullable=False),
        sa.Column("donnees", postgresql.JSONB(), nullable=False),
        sa.Column("statut", sa.String(20), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_parcours_conversation_id", "parcours", ["conversation_id"])
    op.create_index(
        "uq_parcours_actif_par_conversation",
        "parcours",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("statut IN ('en_cours', 'en_pause')"),
    )


def downgrade() -> None:
    op.drop_index("uq_parcours_actif_par_conversation", table_name="parcours")
    op.drop_index("ix_parcours_conversation_id", table_name="parcours")
    op.drop_table("parcours")
    for nom, _ in reversed(COLONNES_ENTREPRISE):
        op.drop_column("entreprises", nom)
