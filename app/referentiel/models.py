"""Référentiel des juridictions : un pays = un déploiement (corpus, règles, devise, calendrier)."""
from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Juridiction(Base):
    __tablename__ = "juridictions"

    code: Mapped[str] = mapped_column(String(2), primary_key=True)  # ISO 3166-1, ex. "CM"
    nom: Mapped[str] = mapped_column(String(100))
    devise: Mapped[str] = mapped_column(String(3))  # ISO 4217, ex. "XAF"
    langue: Mapped[str] = mapped_column(String(5))
    fuseau_horaire: Mapped[str] = mapped_column(String(50))
    active: Mapped[bool] = mapped_column(Boolean, default=False)
