"""Règles fiscales et sociales : des données versionnées, sourcées et datées, jamais du code."""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

OBLIGATION = "obligation"
ALERTE = "alerte"
TYPES = (OBLIGATION, ALERTE)

BROUILLON = "brouillon"
A_VALIDER = "a_valider"
PUBLIEE = "publiee"
RETIREE = "retiree"
STATUTS = (BROUILLON, A_VALIDER, PUBLIEE, RETIREE)
# Statuts montrés aux clients ; « à valider » l'est avec un avertissement.
STATUTS_VISIBLES = (A_VALIDER, PUBLIEE)

# Lot 13 : classement montré dans le coffre (onglet Obligations). Il peut changer sur une version
# déjà chargée, comme le statut : ce n'est pas le contenu juridique de la règle.
FISCAL = "fiscal"
SOCIAL = "social"
DOMAINES = (FISCAL, SOCIAL)

PERIODICITES = {
    "mensuelle": "Chaque mois",
    "trimestrielle": "Chaque trimestre",
    "annuelle": "Chaque année",
    "ponctuelle": "Une fois",
}


class Regle(Base):
    __tablename__ = "regles"
    __table_args__ = (
        UniqueConstraint("juridiction_code", "code", "version", name="uq_regles_juridiction_code_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    juridiction_code: Mapped[str] = mapped_column(ForeignKey("juridictions.code"))
    code: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(20))
    impot: Mapped[str] = mapped_column(String(40))
    domaine: Mapped[str] = mapped_column(String(10), default=FISCAL, server_default=FISCAL)
    titre: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    condition: Mapped[dict] = mapped_column(JSONB)
    periodicite: Mapped[str | None] = mapped_column(String(20), default=None)
    echeance: Mapped[str | None] = mapped_column(String(200), default=None)
    # Échéance calculable (lot 5), voir app/calendrier/dates.py ; absente = « date à confirmer ».
    echeance_calcul: Mapped[dict | None] = mapped_column(JSONB, default=None)
    source_texte: Mapped[str | None] = mapped_column(String(300), default=None)
    source_article: Mapped[str | None] = mapped_column(String(100), default=None)
    source_url: Mapped[str | None] = mapped_column(String(500), default=None)
    applicable_du: Mapped[date] = mapped_column(Date)
    applicable_au: Mapped[date | None] = mapped_column(Date, default=None)
    statut: Mapped[str] = mapped_column(String(20))
    ordre: Mapped[int] = mapped_column(Integer, default=100)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
