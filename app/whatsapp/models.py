"""WhatsApp : messages reçus (pour ignorer les doublons) et boîte d'envoi des réponses."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

A_ENVOYER = "a_envoyer"
ENVOYE = "envoye"
ECHEC = "echec"
ANNULE = "annule"  # Rappel remplacé par un plus urgent avant l'envoi.


class WhatsappRecu(Base):
    """Chaque message reçu de Meta, par son identifiant : Meta peut renvoyer le même plusieurs fois."""

    __tablename__ = "whatsapp_recus"

    wamid: Mapped[str] = mapped_column(String(200), primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    recu_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WhatsappEnvoi(Base):
    __tablename__ = "whatsapp_envois"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    destinataire: Mapped[str] = mapped_column(String(32))
    # Lot 10 : entreprise et rappel concernés ; nom du modèle Meta si c'est un message hors fenêtre.
    entreprise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entreprises.id"), default=None, index=True)
    rappel_id: Mapped[int | None] = mapped_column(ForeignKey("rappels.id"), default=None)
    modele: Mapped[str | None] = mapped_column(String(100), default=None)
    # Le message tel qu'envoyé à Meta (sans le destinataire) : texte, boutons ou liste.
    contenu: Mapped[dict] = mapped_column(JSONB)
    statut: Mapped[str] = mapped_column(String(20), default=A_ENVOYER, index=True)
    essais: Mapped[int] = mapped_column(Integer, default=0)
    erreur: Mapped[str | None] = mapped_column(String(500), default=None)
    wamid: Mapped[str | None] = mapped_column(String(200), default=None, index=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    envoye_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
