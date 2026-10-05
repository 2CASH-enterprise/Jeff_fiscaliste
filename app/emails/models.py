"""Boîte d'envoi des emails : écrits en base avec le reste, envoyés ensuite par Celery.

Ainsi un email n'existe que si l'action qui l'a produit (rappel, code) est bien enregistrée,
et un envoi raté peut être retenté sans rien perdre.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

A_ENVOYER = "a_envoyer"
ENVOYE = "envoye"
ECHEC = "echec"  # Trois essais ratés.
ANNULE = "annule"  # Plus utile avant l'envoi (rappel remplacé par un plus urgent).
STATUTS = (A_ENVOYER, ENVOYE, ECHEC, ANNULE)

CODE = "code"
RAPPEL = "rappel"
TEST = "test"


class Email(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(20))
    entreprise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entreprises.id"), default=None, index=True)
    rappel_id: Mapped[int | None] = mapped_column(ForeignKey("rappels.id"), default=None)
    destinataire: Mapped[str] = mapped_column(String(254))
    objet: Mapped[str] = mapped_column(String(200))
    texte: Mapped[str] = mapped_column(Text)
    html: Mapped[str] = mapped_column(Text)
    statut: Mapped[str] = mapped_column(String(20), default=A_ENVOYER, index=True)
    essais: Mapped[int] = mapped_column(Integer, default=0)
    erreur: Mapped[str | None] = mapped_column(String(500), default=None)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    envoye_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
