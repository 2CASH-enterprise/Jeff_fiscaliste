"""Documents déposés dans le coffre fiscal (lot 15).

Le fichier est sur le disque (volume Docker jeff_documents) sous un nom choisi par Jeff ; la base
garde le nom d'origine, le classement (type et mois), la taille et l'empreinte SHA-256.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

FACTURE = "facture"
PAIE = "paie"
DECLARATION = "declaration"
ATTESTATION = "attestation"
AUTRE = "autre"
TYPES = (FACTURE, PAIE, DECLARATION, ATTESTATION, AUTRE)

PDF = "pdf"
JPEG = "jpeg"
PNG = "png"
FORMATS = (PDF, JPEG, PNG)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("type_document IN ('facture', 'paie', 'declaration', 'attestation', 'autre')", name="ck_documents_type"),
        CheckConstraint("format IN ('pdf', 'jpeg', 'png')", name="ck_documents_format"),
        CheckConstraint("taille > 0", name="ck_documents_taille"),
        CheckConstraint("extract(day from mois) = 1", name="ck_documents_mois"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entreprise_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entreprises.id"), index=True)
    type_document: Mapped[str] = mapped_column(String(20), default=AUTRE)
    mois: Mapped[date] = mapped_column(Date)  # Toujours le 1er du mois concerné.
    nom: Mapped[str] = mapped_column(String(150))  # Nom d'origine, nettoyé, pour l'affichage.
    format: Mapped[str] = mapped_column(String(10))
    taille: Mapped[int] = mapped_column(Integer)  # Octets.
    empreinte: Mapped[str] = mapped_column(String(64))
    session_espace_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("sessions_espace.id"), default=None)
    depose_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
