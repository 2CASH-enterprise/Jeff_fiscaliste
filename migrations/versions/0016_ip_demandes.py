"""Lot 17 — adresse IP des demandes de code (limite par IP du coffre public).

Revision ID: 0016_ip_demandes
Revises: 0015_documents
"""
import sqlalchemy as sa
from alembic import op

revision = "0016_ip_demandes"
down_revision = "0015_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("demandes_connexion", sa.Column("ip", sa.String(45), nullable=True))
    op.create_index("ix_demandes_connexion_ip", "demandes_connexion", ["ip"])


def downgrade() -> None:
    op.drop_index("ix_demandes_connexion_ip", table_name="demandes_connexion")
    op.drop_column("demandes_connexion", "ip")
