"""Relier une nouvelle conversation (WhatsApp ou un autre navigateur) à un profil existant (lot 9).

Le client donne l'adresse email confirmée de son profil ; Jeff y envoie un code. Sans ce code,
rien n'est relié. Jeff répond la même chose que l'adresse soit connue ou non : on ne révèle
jamais si une entreprise existe.
"""
import hmac
import re
import uuid
import secrets
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation import confirmation
from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, TERMINE, Conversation, Parcours
from app.conversation.normalisation import normaliser
from app.conversation.reponse import Reponse
from app.core.config import get_settings
from app.emails.composition import email_liaison
from app.entreprises.models import Entreprise

TYPE = "liaison"
ETAPE_EMAIL = "email"
ETAPE_CODE = "code"
ETAPE_CHOIX = "choix"  # Lot 11 : adresse confirmée pour plusieurs entreprises.
DEJA = {"deja", "j ai deja un profil", "deja un profil", "j ai un profil"}


def demarrer(session: Session, conversation: Conversation) -> Reponse:
    parcours = Parcours(conversation_id=conversation.id, type=TYPE, etape=ETAPE_EMAIL, donnees={"renvois": 0})
    session.add(parcours)
    session.flush()
    return question(parcours)


def question(parcours: Parcours) -> Reponse:
    if parcours.etape == ETAPE_EMAIL:
        return Reponse(mf.LIAISON_EMAIL)
    if parcours.etape == ETAPE_CHOIX:
        return Reponse(mf.LIAISON_CHOIX, choix_entreprises(parcours))
    return Reponse(mf.LIAISON_CODE_ATTENDU, list(mf.CHOIX_CODE))


def entreprises_confirmees(session: Session, email: str) -> list[Entreprise]:
    """Toutes les entreprises de la juridiction qui ont confirmé cette adresse, par ordre alphabétique."""
    return list(session.scalars(
        select(Entreprise).where(
            Entreprise.juridiction_code == get_settings().juridiction,
            Entreprise.email == email,
            Entreprise.email_confirme_le.is_not(None),
        ).order_by(Entreprise.raison_sociale, Entreprise.cree_le)
    ))


def entreprise_confirmee(session: Session, email: str) -> Entreprise | None:
    trouvees = entreprises_confirmees(session, email)
    return trouvees[0] if trouvees else None


def identifiants(donnees: dict) -> list[str]:
    """Entreprises candidates ; « entreprise_id » vient d'une liaison commencée avant le lot 11."""
    if "entreprise_ids" in donnees:
        return donnees["entreprise_ids"]
    return [donnees["entreprise_id"]] if donnees.get("entreprise_id") else []


def choix_entreprises(parcours: Parcours) -> list[tuple[str, str]]:
    return [(str(numero), nom) for numero, nom in enumerate(parcours.donnees["noms"], start=1)]


def nouveau_code(session: Session, parcours: Parcours, entreprises: list[Entreprise]) -> None:
    """Un code n'est envoyé que si l'adresse est connue ; sinon aucun code ne peut convenir."""
    donnees = {**parcours.donnees, "expire_le": (confirmation.maintenant() + confirmation.DUREE).isoformat(), "essais": 0}
    donnees["empreinte"] = None
    if entreprises:
        code = f"{secrets.randbelow(10**6):06d}"
        donnees["empreinte"] = confirmation.empreinte(parcours, code)
        email_liaison(session, entreprises, code)
    parcours.donnees = donnees


def toujours_valide(entreprise: Entreprise | None, email: str) -> bool:
    return entreprise is not None and entreprise.email == email and entreprise.email_confirme_le is not None


def relier(conversation: Conversation, parcours: Parcours, entreprise: Entreprise) -> Reponse:
    conversation.entreprise_id = entreprise.id
    parcours.statut = TERMINE
    return Reponse(mf.LIAISON_OK.format(raison_sociale=entreprise.raison_sociale), list(mf.MENU))


def avancer(session: Session, conversation: Conversation, parcours: Parcours, texte: str) -> Reponse:
    from app.conversation.onboarding import ReponseInvalide, lire_email

    if parcours.etape == ETAPE_EMAIL:
        try:
            email = lire_email(texte, session)
        except ReponseInvalide:
            email = None
        if email is None:
            return Reponse(mf.ERR_EMAIL)
        entreprises = entreprises_confirmees(session, email)
        parcours.donnees = {**parcours.donnees, "email": email, "entreprise_ids": [str(e.id) for e in entreprises]}
        parcours.etape = ETAPE_CODE
        nouveau_code(session, parcours, entreprises)
        return Reponse(mf.LIAISON_CODE_ENVOYE, list(mf.CHOIX_CODE))

    donnees = parcours.donnees
    candidates = [session.get(Entreprise, uuid.UUID(i)) for i in identifiants(donnees)]

    if parcours.etape == ETAPE_CHOIX:
        choix = normaliser(texte)
        if not choix.isdigit() or not 1 <= int(choix) <= len(candidates):
            return Reponse(mf.ERR_CHOIX, choix_entreprises(parcours))
        entreprise = candidates[int(choix) - 1]
        if not toujours_valide(entreprise, donnees["email"]):
            parcours.statut = ABANDONNE
            return Reponse(mf.LIAISON_ANNULEE, list(mf.MENU))
        return relier(conversation, parcours, entreprise)

    if normaliser(texte) == "renvoyer":
        if donnees["renvois"] >= confirmation.RENVOIS_MAX:
            return Reponse(mf.CODE_TROP_DE_RENVOIS)
        parcours.donnees = {**donnees, "renvois": donnees["renvois"] + 1}
        nouveau_code(session, parcours, [e for e in candidates if e is not None])
        return Reponse(mf.LIAISON_CODE_ENVOYE, list(mf.CHOIX_CODE))

    code = re.sub(r"[\s.\-]", "", texte)
    if not re.fullmatch(r"\d{6}", code):
        return Reponse(mf.CODE_FORMAT, list(mf.CHOIX_CODE))
    if confirmation.maintenant() > datetime.fromisoformat(donnees["expire_le"]):
        return Reponse(mf.CODE_EXPIRE, list(mf.CHOIX_CODE))
    attendu = donnees["empreinte"]
    if attendu is None or not hmac.compare_digest(confirmation.empreinte(parcours, code), attendu):
        essais = donnees["essais"] + 1
        parcours.donnees = {**donnees, "essais": essais}
        if essais >= confirmation.ESSAIS_MAX:
            parcours.statut = ABANDONNE
            return Reponse(mf.LIAISON_TROP_D_ESSAIS, list(mf.MENU))
        return Reponse(mf.CODE_FAUX, list(mf.CHOIX_CODE))

    valides = [e for e in candidates if toujours_valide(e, donnees["email"])]
    if not valides:
        # L'adresse a changé entre-temps : on ne relie rien.
        parcours.statut = ABANDONNE
        return Reponse(mf.LIAISON_ANNULEE, list(mf.MENU))
    if len(valides) == 1:
        return relier(conversation, parcours, valides[0])
    parcours.donnees = {**donnees, "entreprise_ids": [str(e.id) for e in valides], "noms": [e.raison_sociale for e in valides]}
    parcours.etape = ETAPE_CHOIX
    return question(parcours)
