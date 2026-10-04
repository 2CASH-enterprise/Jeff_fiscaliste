"""Rappels d'échéances : préparés chaque matin, puis remis au client sur un canal."""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

A_ENVOYER = "a_envoyer"
ENVOYE = "envoye"
IGNORE = "ignore"  # Remplacé par un rappel plus urgent avant d'avoir été remis.
EXPIRE = "expire"  # Échéance passée avant que le client ne revienne.
STATUTS = (A_ENVOYER, ENVOYE, IGNORE, EXPIRE)


class Rappel(Base):
    __tablename__ = "rappels"
    __table_args__ = (
        # Jamais deux fois le même rappel, même si la tâche du matin tourne deux fois.
        UniqueConstraint(
            "entreprise_id", "regle_code", "date_limite", "palier", name="uq_rappels_entreprise_regle_date_palier"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    regle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("regles.id"))
    # Le code reste le même d'une version de règle à l'autre : il sert à éviter les doublons.
    regle_code: Mapped[str] = mapped_column(String(60))
    periode: Mapped[str] = mapped_column(String(50))
    date_limite: Mapped[date] = mapped_column(Date)
    palier: Mapped[int] = mapped_column(Integer)  # Nombre de jours avant l'échéance : 7 ou 2.
    date_prevue: Mapped[date] = mapped_column(Date)
    canal: Mapped[str] = mapped_column(String(20))
    statut: Mapped[str] = mapped_column(String(20), default=A_ENVOYER)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"), default=None)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    envoye_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
