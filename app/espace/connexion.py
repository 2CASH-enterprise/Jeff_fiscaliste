"""Connexion au coffre fiscal par code email, puis session de 30 jours (lot 12).

Mêmes règles que la confirmation d'adresse (lot 8) : code à 6 chiffres valable 15 minutes,
5 essais, 3 renvois. Jeff répond la même chose que l'adresse soit connue ou non ; seules les
entreprises dont cette adresse est confirmée donnent accès. Ni le code ni le jeton de session
ne sont gardés en clair.
"""
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.conversation.confirmation import DUREE, ESSAIS_MAX, RENVOIS_MAX, maintenant
from app.conversation.liaison import entreprises_confirmees
from app.emails.composition import email_connexion
from app.entreprises.models import Entreprise
from app.espace.models import ABANDONNEE, EN_COURS, UTILISEE, DemandeConnexion, SessionEspace

DUREE_SESSION = timedelta(days=30)
DEMANDES_PAR_HEURE = 5
JETON_MAX = 100
USER_AGENT_MAX = 200

# Résultats de la vérification d'un code.
OK = "ok"
FORMAT = "format"
EXPIRE = "expire"
FAUX = "faux"
TROP_D_ESSAIS = "trop_d_essais"
AUCUNE = "aucune"
INVALIDE = "invalide"


class TropDeDemandes(Exception):
    pass


def empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode()).hexdigest()


def empreinte_code(demande: DemandeConnexion, code: str) -> str:
    return empreinte(f"{demande.id}:{code}")


# --- Demande de code ------------------------------------------------------------------------------

def envoyer_code(session: Session, demande: DemandeConnexion) -> None:
    """Nouveau code, essais remis à zéro. Rien n'est envoyé si l'adresse n'ouvre aucune entreprise."""
    demande.expire_le = maintenant() + DUREE
    demande.essais = 0
    demande.empreinte = None
    entreprises = entreprises_confirmees(session, demande.email)
    if entreprises:
        code = f"{secrets.randbelow(10**6):06d}"
        demande.empreinte = empreinte_code(demande, code)
        email_connexion(session, entreprises, code)


def demander_code(session: Session, email: str) -> DemandeConnexion:
    depuis = maintenant() - timedelta(hours=1)
    recentes = session.scalar(
        select(func.count()).select_from(DemandeConnexion).where(
            DemandeConnexion.email == email, DemandeConnexion.cree_le > depuis
        )
    )
    if recentes >= DEMANDES_PAR_HEURE:
        raise TropDeDemandes
    demande = DemandeConnexion(id=uuid.uuid4(), email=email, essais=0, renvois=0, statut=EN_COURS, expire_le=maintenant())
    session.add(demande)
    envoyer_code(session, demande)
    session.flush()
    return demande


def demande_en_cours(session: Session, identifiant: str | None) -> DemandeConnexion | None:
    try:
        demande = session.get(DemandeConnexion, uuid.UUID(identifiant or ""))
    except ValueError:
        return None
    if demande is None or demande.statut != EN_COURS:
        return None
    return demande


def renvoyer(session: Session, demande: DemandeConnexion) -> bool:
    if demande.renvois >= RENVOIS_MAX:
        return False
    demande.renvois += 1
    envoyer_code(session, demande)
    return True


def verifier_code(session: Session, demande: DemandeConnexion, texte: str) -> tuple[str, list[Entreprise]]:
    if demande.statut != EN_COURS:
        return INVALIDE, []
    code = re.sub(r"[\s.\-]", "", texte or "")
    if not re.fullmatch(r"\d{6}", code):
        return FORMAT, []
    if maintenant() > demande.expire_le:
        return EXPIRE, []
    if demande.empreinte is None or not hmac.compare_digest(empreinte_code(demande, code), demande.empreinte):
        demande.essais += 1
        if demande.essais >= ESSAIS_MAX:
            demande.statut = ABANDONNEE
            return TROP_D_ESSAIS, []
        return FAUX, []
    entreprises = entreprises_confirmees(session, demande.email)
    if not entreprises:
        # L'adresse a été changée ou n'est plus confirmée depuis l'envoi du code.
        demande.statut = ABANDONNEE
        return AUCUNE, []
    demande.statut = UTILISEE
    return OK, entreprises


# --- Session ------------------------------------------------------------------------------------

def ouvrir_session(
    session: Session, email: str, entreprises: list[Entreprise], user_agent: str | None
) -> tuple[str, SessionEspace]:
    """Le jeton n'est rendu qu'une fois, pour le cookie ; la base n'en garde que l'empreinte."""
    jeton = secrets.token_urlsafe(32)
    instant = maintenant()
    ouverte = SessionEspace(
        empreinte_jeton=empreinte(jeton),
        email=email,
        entreprise_id=entreprises[0].id if len(entreprises) == 1 else None,
        user_agent=(user_agent or "")[:USER_AGENT_MAX] or None,
        expire_le=instant + DUREE_SESSION,
        derniere_activite_le=instant,
    )
    session.add(ouverte)
    session.flush()
    return jeton, ouverte


def session_active(session: Session, jeton: str | None) -> SessionEspace | None:
    if not jeton or len(jeton) > JETON_MAX:
        return None
    instant = maintenant()
    trouvee = session.scalar(
        select(SessionEspace).where(
            SessionEspace.empreinte_jeton == empreinte(jeton),
            SessionEspace.fermee_le.is_(None),
            SessionEspace.expire_le > instant,
        )
    )
    if trouvee is not None:
        trouvee.derniere_activite_le = instant
    return trouvee


def entreprises_de(session: Session, ouverte: SessionEspace) -> list[Entreprise]:
    """Entreprises accessibles, recalculées à chaque page : un changement d'adresse coupe l'accès."""
    return entreprises_confirmees(session, ouverte.email)


def entreprise_courante(session: Session, ouverte: SessionEspace) -> Entreprise | None:
    if ouverte.entreprise_id is None:
        return None
    for entreprise in entreprises_de(session, ouverte):
        if entreprise.id == ouverte.entreprise_id:
            return entreprise
    ouverte.entreprise_id = None
    return None


def choisir(session: Session, ouverte: SessionEspace, identifiant: str) -> bool:
    for entreprise in entreprises_de(session, ouverte):
        if str(entreprise.id) == identifiant:
            ouverte.entreprise_id = entreprise.id
            return True
    return False


def fermer(ouverte: SessionEspace) -> None:
    ouverte.fermee_le = maintenant()
