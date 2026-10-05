"""Lot 14 — préférences de rappels dans le coffre et origine des modifications.

- entreprises.rappels_email : le client peut couper les rappels par email (l'adresse reste confirmée).
- modifications_entreprise.origine : « conversation » (lots 6 et 11) ou « coffre » (lot 14),
  avec la session du coffre qui a fait le changement.

Revision ID: 0014_preferences_rappels
Revises: 0013_domaine_regles
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_preferences_rappels"
down_revision = "0013_domaine_regles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entreprises", sa.Column("rappels_email", sa.Boolean(), server_default=sa.text("true"), nullable=False))
    op.add_column(
        "modifications_entreprise",
        sa.Column("origine", sa.String(20), server_default="conversation", nullable=False),
    )
    op.create_check_constraint(
        "ck_modifications_entreprise_origine", "modifications_entreprise", "origine IN ('conversation', 'coffre')"
    )
    op.add_column(
        "modifications_entreprise",
        sa.Column("session_espace_id", sa.BigInteger(), sa.ForeignKey("sessions_espace.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("modifications_entreprise", "session_espace_id")
    op.drop_constraint("ck_modifications_entreprise_origine", "modifications_entreprise", type_="check")
    op.drop_column("modifications_entreprise", "origine")
    op.drop_column("entreprises", "rappels_email")
