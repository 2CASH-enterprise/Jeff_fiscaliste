"""Lot 13 — domaine des règles (fiscal ou social), pour l'onglet Obligations du coffre.

Les règles déjà chargées reçoivent leur domaine ici ; le fichier de règles le porte ensuite.

Revision ID: 0013_domaine_regles
Revises: 0012_espace
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_domaine_regles"
down_revision = "0012_espace"
branch_labels = None
depends_on = None

SOCIALES = ("SALAIRES_RETENUES_DIPE", "CNPS_IMMATRICULATION_EMPLOYEUR")


def upgrade() -> None:
    op.add_column("regles", sa.Column("domaine", sa.String(10), server_default="fiscal", nullable=False))
    op.create_check_constraint("ck_regles_domaine", "regles", "domaine IN ('fiscal', 'social')")
    op.execute(
        sa.text("UPDATE regles SET domaine = 'social' WHERE juridiction_code = 'CM' AND code IN :codes")
        .bindparams(sa.bindparam("codes", value=SOCIALES, expanding=True))
    )


def downgrade() -> None:
    op.drop_constraint("ck_regles_domaine", "regles", type_="check")
    op.drop_column("regles", "domaine")
