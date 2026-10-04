"""Conversations et messages : un historique commun à tous les canaux."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

CANAL_WEB = "web"
CANAL_WHATSAPP = "whatsapp"

ENTRANT = "entrant"
SORTANT = "sortant"

EN_COURS = "en_cours"
EN_PAUSE = "en_pause"
TERMINE = "termine"
ABANDONNE = "abandonne"


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("canal", "identifiant_externe", name="uq_conversations_canal_identifiant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canal: Mapped[str] = mapped_column(String(20))
    # Jeton de session web, ou numéro WhatsApp plus tard.
    identifiant_externe: Mapped[str] = mapped_column(String(100))
    # Rattachement à une entreprise après l'onboarding (prochains lots).
    entreprise_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entreprises.id"), default=None, index=True
    )
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    sens: Mapped[str] = mapped_column(String(10))  # entrant (client) ou sortant (Jeff)
    texte: Mapped[str] = mapped_column(Text)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Parcours(Base):
    """Questionnaire en cours dans une conversation (onboarding, puis déclarations)."""

    __tablename__ = "parcours"
    __table_args__ = (
        # Un seul parcours actif (en cours ou en pause) par conversation.
        Index(
            "uq_parcours_actif_par_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("statut IN ('en_cours', 'en_pause')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    etape: Mapped[str] = mapped_column(String(50))
    donnees: Mapped[dict] = mapped_column(JSONB, default=dict)
    statut: Mapped[str] = mapped_column(String(20), default=EN_COURS)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
