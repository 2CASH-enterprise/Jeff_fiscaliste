"""Connexion au coffre fiscal : demandes de code et sessions (lot 12).

Ni le code ni le jeton de session ne sont gardés en clair : seulement leur empreinte SHA-256.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

EN_COURS = "en_cours"
UTILISEE = "utilisee"
ABANDONNEE = "abandonnee"  # Trop d'essais, ou plus aucune entreprise confirmée pour l'adresse.
STATUTS_DEMANDE = (EN_COURS, UTILISEE, ABANDONNEE)


class DemandeConnexion(Base):
    __tablename__ = "demandes_connexion"

    # Identifiant aléatoire : c'est lui que garde le cookie du navigateur entre l'email et le code.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), index=True)
    # Lot 17 : adresse IP du demandeur (limite de demandes par IP, coffre public).
    ip: Mapped[str | None] = mapped_column(String(45), default=None, index=True)
    # Vide si l'adresse n'est confirmée pour aucune entreprise : aucun code ne peut alors convenir.
    empreinte: Mapped[str | None] = mapped_column(String(64), default=None)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    essais: Mapped[int] = mapped_column(Integer, default=0)
    renvois: Mapped[int] = mapped_column(Integer, default=0)
    statut: Mapped[str] = mapped_column(String(20), default=EN_COURS)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionEspace(Base):
    __tablename__ = "sessions_espace"
    __table_args__ = (UniqueConstraint("empreinte_jeton", name="uq_sessions_espace_empreinte_jeton"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    empreinte_jeton: Mapped[str] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(254), index=True)
    # Entreprise affichée ; vide tant que le client n'a pas choisi (adresse partagée).
    entreprise_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("entreprises.id"), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(200), default=None)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    derniere_activite_le: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fermee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
