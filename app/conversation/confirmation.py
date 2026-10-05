"""Confirmation de l'adresse email par un code à 6 chiffres (lot 8).

Le code est envoyé par email et recopié dans la conversation. Seule son empreinte est gardée
dans le parcours. 15 minutes de validité, 5 essais, 3 renvois au plus.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, TERMINE, Conversation, Parcours
from app.conversation.normalisation import normaliser
from app.conversation.reponse import Reponse
from app.emails.composition import email_code
from app.entreprises.models import Entreprise

TYPE = "confirmation_email"
ETAPE = "code"
DUREE = timedelta(minutes=15)
ESSAIS_MAX = 5
RENVOIS_MAX = 3


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def empreinte(parcours: Parcours, code: str) -> str:
    return hashlib.sha256(f"{parcours.id}:{code}".encode()).hexdigest()


def nouveau_code(session: Session, parcours: Parcours, entreprise: Entreprise) -> None:
    code = f"{secrets.randbelow(10**6):06d}"
    parcours.donnees = {
        **parcours.donnees,
        "empreinte": empreinte(parcours, code),
        "expire_le": (maintenant() + DUREE).isoformat(),
        "essais": 0,
    }
    email_code(session, entreprise.id, entreprise.email, code)


def demarrer(session: Session, conversation: Conversation, entreprise: Entreprise) -> Reponse:
    parcours = Parcours(
        conversation_id=conversation.id, type=TYPE, etape=ETAPE, donnees={"email": entreprise.email, "renvois": 0}
    )
    session.add(parcours)
    session.flush()
    nouveau_code(session, parcours, entreprise)
    return Reponse(mf.CODE_ENVOYE.format(email=entreprise.email), list(mf.CHOIX_CODE))


def question(parcours: Parcours) -> Reponse:
    return Reponse(mf.CODE_ATTENDU.format(email=parcours.donnees["email"]), list(mf.CHOIX_CODE))


def avancer(session: Session, conversation: Conversation, parcours: Parcours, texte: str) -> Reponse:
    entreprise = session.get(Entreprise, conversation.entreprise_id)
    donnees = parcours.donnees
    if entreprise.email != donnees["email"]:
        # L'adresse a changé entre-temps : ce code ne vaut plus rien.
        parcours.statut = ABANDONNE
        return Reponse(mf.CONFIRMATION_ANNULEE, list(mf.MENU))

    if normaliser(texte) == "renvoyer":
        if donnees["renvois"] >= RENVOIS_MAX:
            return Reponse(mf.CODE_TROP_DE_RENVOIS)
        parcours.donnees = {**donnees, "renvois": donnees["renvois"] + 1}
        nouveau_code(session, parcours, entreprise)
        return Reponse(mf.CODE_RENVOYE.format(email=entreprise.email), list(mf.CHOIX_CODE))

    code = re.sub(r"[\s.\-]", "", texte)
    if not re.fullmatch(r"\d{6}", code):
        return Reponse(mf.CODE_FORMAT, list(mf.CHOIX_CODE))
    if maintenant() > datetime.fromisoformat(donnees["expire_le"]):
        return Reponse(mf.CODE_EXPIRE, list(mf.CHOIX_CODE))
    if not hmac.compare_digest(empreinte(parcours, code), donnees["empreinte"]):
        essais = donnees["essais"] + 1
        parcours.donnees = {**donnees, "essais": essais}
        if essais >= ESSAIS_MAX:
            parcours.statut = ABANDONNE
            return Reponse(mf.CODE_TROP_D_ESSAIS, list(mf.MENU))
        return Reponse(mf.CODE_FAUX, list(mf.CHOIX_CODE))

    entreprise.email_confirme_le = maintenant()
    parcours.statut = TERMINE
    return Reponse(mf.EMAIL_CONFIRME.format(email=entreprise.email), list(mf.MENU))
