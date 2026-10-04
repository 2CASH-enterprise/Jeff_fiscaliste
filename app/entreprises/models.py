"""Entreprise cliente : rattachée à une seule juridiction, identifiée par son NIU dans ce pays."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Entreprise(Base):
    __tablename__ = "entreprises"
    __table_args__ = (UniqueConstraint("juridiction_code", "niu", name="uq_entreprises_juridiction_niu"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    juridiction_code: Mapped[str] = mapped_column(ForeignKey("juridictions.code"))
    niu: Mapped[str] = mapped_column(String(20))
    raison_sociale: Mapped[str] = mapped_column(String(200))
    # Distributeur ou cabinet rattaché (phase P6) ; la table des distributeurs viendra plus tard.
    distributeur_id: Mapped[uuid.UUID | None] = mapped_column(default=None, index=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
