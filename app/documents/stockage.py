"""Dépôt, classement et suppression des documents du coffre (lot 15).

Règles du porteur : PDF, JPEG ou PNG, 10 Mo par fichier, 500 Mo par entreprise. Le format est
reconnu au contenu du fichier (ses premiers octets), jamais à son nom ni à ce que dit le navigateur.
Le fichier est rangé sous un nom choisi par Jeff (identifiant du document) : rien de ce que
fournit le client n'entre dans le chemin sur le disque.
"""
import hashlib
import os
import re
import unicodedata
import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.documents.models import JPEG, PDF, PNG, TYPES, Document
from app.entreprises.models import COFFRE, Entreprise
from app.rappels.preferences import tracer

MO = 1024 * 1024
TAILLE_MAX = 10 * MO
QUOTA = 500 * MO
BLOC = MO
NOM_MAX = 150

SIGNATURES = ((b"%PDF-", PDF), (b"\xff\xd8\xff", JPEG), (b"\x89PNG\r\n\x1a\n", PNG))
EXTENSIONS = {PDF: "pdf", JPEG: "jpg", PNG: "png"}
TYPES_MIME = {PDF: "application/pdf", JPEG: "image/jpeg", PNG: "image/png"}

# Traces dans l'historique de l'entreprise (table modifications_entreprise).
DEPOSE = "document_depose"
RECLASSE = "document_classement"
SUPPRIME = "document_supprime"

# Raisons d'un refus, reprises dans l'adresse de retour (?info=…).
VIDE = "vide"
FORMAT = "format"
TAILLE = "taille"
QUOTA_ATTEINT = "quota"


class DepotRefuse(Exception):
    def __init__(self, raison: str):
        super().__init__(raison)
        self.raison = raison


def dossier() -> Path:
    return Path(get_settings().documents_dossier)


def chemin(document: Document) -> Path:
    return dossier() / str(document.entreprise_id) / f"{document.id}.{EXTENSIONS[document.format]}"


def detecter_format(debut: bytes) -> str | None:
    for signature, format_ in SIGNATURES:
        if debut.startswith(signature):
            return format_
    return None


def nettoyer_nom(nom: str | None, format_: str) -> str:
    """Nom affiché : sans chemin ni caractère de contrôle, 150 caractères au plus, extension gardée."""
    nom = re.split(r"[\\/]", nom or "")[-1]
    nom = "".join(c for c in unicodedata.normalize("NFC", nom) if unicodedata.category(c)[0] != "C")
    nom = " ".join(nom.split()).strip(" .")
    if not nom:
        nom = f"document.{EXTENSIONS[format_]}"
    if len(nom) > NOM_MAX:
        base, point, extension = nom.rpartition(".")
        if point and 0 < len(extension) <= 5:
            nom = base[: NOM_MAX - len(extension) - 1].rstrip() + "." + extension
        else:
            nom = nom[:NOM_MAX]
    return nom


def utilise(session: Session, entreprise_id) -> int:
    return session.scalar(
        select(func.coalesce(func.sum(Document.taille), 0)).where(Document.entreprise_id == entreprise_id)
    )


def description(document: Document) -> dict:
    return {"nom": document.nom, "type": document.type_document, "mois": document.mois.strftime("%Y-%m")}


def deposer(session: Session, entreprise: Entreprise, fichier, nom_origine: str | None, type_document: str,
            mois: date, session_espace_id: int | None) -> Document:
    """Lit le fichier par blocs (jamais plus de 10 Mo), le vérifie, puis le range et l'enregistre."""
    if type_document not in TYPES or mois.day != 1:
        raise ValueError("classement invalide")
    rangement = dossier() / str(entreprise.id)
    rangement.mkdir(parents=True, exist_ok=True)
    temporaire = rangement / f".depot-{uuid.uuid4().hex}"
    empreinte, taille, debut = hashlib.sha256(), 0, b""
    try:
        with open(temporaire, "wb") as sortie:
            while bloc := fichier.read(BLOC):
                taille += len(bloc)
                if taille > TAILLE_MAX:
                    raise DepotRefuse(TAILLE)
                if len(debut) < 16:
                    debut += bloc[: 16 - len(debut)]
                empreinte.update(bloc)
                sortie.write(bloc)
        if taille == 0:
            raise DepotRefuse(VIDE)
        format_ = detecter_format(debut)
        if format_ is None:
            raise DepotRefuse(FORMAT)
        if utilise(session, entreprise.id) + taille > QUOTA:
            raise DepotRefuse(QUOTA_ATTEINT)
        document = Document(
            id=uuid.uuid4(),
            entreprise_id=entreprise.id,
            type_document=type_document,
            mois=mois,
            nom=nettoyer_nom(nom_origine, format_),
            format=format_,
            taille=taille,
            empreinte=empreinte.hexdigest(),
            session_espace_id=session_espace_id,
        )
        session.add(document)
        tracer(session, entreprise.id, DEPOSE, None, description(document), COFFRE, session_espace_id=session_espace_id)
        session.flush()
        os.replace(temporaire, chemin(document))
        return document
    finally:
        temporaire.unlink(missing_ok=True)


def reclasser(session: Session, document: Document, type_document: str, mois: date,
              session_espace_id: int | None) -> bool:
    if type_document not in TYPES or mois.day != 1:
        raise ValueError("classement invalide")
    if (document.type_document, document.mois) == (type_document, mois):
        return False
    avant = description(document)
    document.type_document, document.mois = type_document, mois
    tracer(session, document.entreprise_id, RECLASSE, avant, description(document), COFFRE,
           session_espace_id=session_espace_id)
    session.flush()
    return True


def supprimer(session: Session, document: Document, session_espace_id: int | None) -> None:
    """Effacement définitif : la ligne et le fichier ; seule une trace (nom, type, mois) reste."""
    fichier = chemin(document)
    tracer(session, document.entreprise_id, SUPPRIME, description(document), None, COFFRE,
           session_espace_id=session_espace_id)
    session.delete(document)
    session.flush()
    fichier.unlink(missing_ok=True)
