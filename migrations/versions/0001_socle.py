"""Lot 1 — socle : juridictions (Cameroun) et entreprises.

Revision ID: 0001_socle
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_socle"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    juridictions = op.create_table(
        "juridictions",
        sa.Column("code", sa.String(2), primary_key=True),
        sa.Column("nom", sa.String(100), nullable=False),
        sa.Column("devise", sa.String(3), nullable=False),
        sa.Column("langue", sa.String(5), nullable=False),
        sa.Column("fuseau_horaire", sa.String(50), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.bulk_insert(
        juridictions,
        [
            {
                "code": "CM",
                "nom": "Cameroun",
                "devise": "XAF",
                "langue": "fr",
                "fuseau_horaire": "Africa/Douala",
                "active": True,
            }
        ],
    )
    op.create_table(
        "entreprises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("juridiction_code", sa.String(2), sa.ForeignKey("juridictions.code"), nullable=False),
        sa.Column("niu", sa.String(20), nullable=False),
        sa.Column("raison_sociale", sa.String(200), nullable=False),
        sa.Column("distributeur_id", sa.Uuid(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("juridiction_code", "niu", name="uq_entreprises_juridiction_niu"),
    )
    op.create_index("ix_entreprises_distributeur_id", "entreprises", ["distributeur_id"])


def downgrade() -> None:
    op.drop_index("ix_entreprises_distributeur_id", table_name="entreprises")
    op.drop_table("entreprises")
    op.drop_table("juridictions")
