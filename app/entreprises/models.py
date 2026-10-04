"""Entreprise cliente : rattachée à une seule juridiction, identifiée par son NIU dans ce pays."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Entreprise(Base):
    __tablename__ = "entreprises"
    __table_args__ = (UniqueConstraint("juridiction_code", "niu", name="uq_entreprises_juridiction_niu"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    juridiction_code: Mapped[str] = mapped_column(ForeignKey("juridictions.code"))
    niu: Mapped[str] = mapped_column(String(20))
    raison_sociale: Mapped[str] = mapped_column(String(200))
    # Profil déclaré par le client à l'onboarding (lot 3). Rien n'est déduit ici :
    # régime et TVA sont ce que l'entreprise déclare, « inconnu » ou None accepté.
    forme_juridique: Mapped[str | None] = mapped_column(String(30), default=None)
    secteur: Mapped[str | None] = mapped_column(String(30), default=None)
    chiffre_affaires_annuel: Mapped[int | None] = mapped_column(BigInteger, default=None)  # FCFA HT
    centre_impots: Mapped[str | None] = mapped_column(String(100), default=None)
    regime_declare: Mapped[str | None] = mapped_column(String(20), default=None)
    assujetti_tva_declare: Mapped[bool | None] = mapped_column(Boolean, default=None)
    nombre_salaries: Mapped[int | None] = mapped_column(Integer, default=None)
    numero_employeur_cnps: Mapped[str | None] = mapped_column(String(30), default=None)
    # Distributeur ou cabinet rattaché (phase P6) ; la table des distributeurs viendra plus tard.
    distributeur_id: Mapped[uuid.UUID | None] = mapped_column(default=None, index=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModificationEntreprise(Base):
    """Trace d'une modification du profil : un enregistrement par champ modifié (lot 6)."""

    __tablename__ = "modifications_entreprise"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    # Conversation d'où vient la modification (bulle web, WhatsApp plus tard).
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"), default=None)
    champ: Mapped[str] = mapped_column(String(50))
    # Valeurs telles qu'en base (texte, nombre, oui/non ou vide), gardées avec leur type.
    ancienne_valeur: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), default=None)
    nouvelle_valeur: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), default=None)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
