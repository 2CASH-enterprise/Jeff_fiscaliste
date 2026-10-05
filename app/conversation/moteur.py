"""Moteur conversationnel commun à tous les canaux (bulle web, WhatsApp plus tard).

Il reçoit un texte, enregistre l'échange et renvoie une réponse. Les réponses sont des
messages fixes ; les parcours (onboarding, puis déclarations) sont menés par le code.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.conversation import confirmation, echeances, obligations, onboarding, profil
from app.conversation.models import (
    ABANDONNE,
    EN_COURS,
    EN_PAUSE,
    ENTRANT,
    SORTANT,
    Conversation,
    Message,
)
from app.conversation.normalisation import normaliser
from app.conversation.reponse import Reponse
from app.entreprises.models import Entreprise
from app.rappels.livraison import rappels_a_remettre

LONGUEUR_MAX = 2000

SALUTATIONS = {"bonjour", "bonsoir", "salut", "hello", "coucou", "bjr", "slt", "menu"}

# Choix du menu qui demandent de connaître l'entreprise.
CHOIX_AVEC_PROFIL = {"1", "2", "3", "5"}
CHOIX_OBLIGATIONS = "2"
CHOIX_ECHEANCES = "3"
CHOIX_PROFIL = "5"
MODIFIER = {"modifier", "modifier mon profil"}
CONFIRMER = {"confirmer", "confirmer mon email"}
ANNULATIONS = {profil.TYPE: mf.MODIFICATION_ANNULEE, confirmation.TYPE: mf.CONFIRMATION_ANNULEE}


def question(parcours) -> Reponse:
    """Question en attente d'un parcours, pour le reprendre."""
    if parcours.type == confirmation.TYPE:
        return confirmation.question(parcours)
    return onboarding.question(parcours)

__all__ = ["LONGUEUR_MAX", "MessageVide", "Reponse", "historique", "normaliser", "repondre", "traiter_message"]


class MessageVide(ValueError):
    pass


def trop_long(texte: str) -> bool:
    return len(texte) > LONGUEUR_MAX


def repondre(texte: str) -> Reponse:
    """Réponse au niveau du menu, pour une entreprise déjà connue. Sans effet de bord."""
    if trop_long(texte):
        return Reponse(mf.TROP_LONG)
    mots = normaliser(texte)
    premier_mot = mots.split()[0] if mots else ""
    if premier_mot in SALUTATIONS:
        return Reponse(mf.ACCUEIL, list(mf.MENU))
    for valeur, libelle in mf.MENU:
        if mots == valeur:
            return Reponse(mf.BIENTOT.format(libelle=libelle))
    return Reponse(mf.INCOMPRIS)


def decider(session: Session, conversation: Conversation, texte: str) -> Reponse:
    """Choisit la réponse en tenant compte du parcours en cours et du profil de l'entreprise."""
    if trop_long(texte):
        return Reponse(mf.TROP_LONG)
    mots = normaliser(texte)
    parcours = onboarding.parcours_actif(session, conversation)

    if parcours is not None and parcours.statut == EN_COURS:
        if mots == "menu":
            parcours.statut = EN_PAUSE
            return Reponse(mf.PAUSE, list(mf.MENU))
        if mots == "annuler":
            parcours.statut = ABANDONNE
            annule = ANNULATIONS.get(parcours.type, mf.ANNULE)
            return Reponse(annule, list(mf.MENU))
        if parcours.type == profil.TYPE:
            return profil.avancer(session, conversation, parcours, texte)
        if parcours.type == confirmation.TYPE:
            return confirmation.avancer(session, conversation, parcours, texte)
        return onboarding.avancer(session, conversation, parcours, texte)

    sans_profil = conversation.entreprise_id is None

    if parcours is not None and parcours.statut == EN_PAUSE:
        reprise_modification = parcours.type == profil.TYPE and mots in MODIFIER
        reprise_confirmation = parcours.type == confirmation.TYPE and mots in CONFIRMER
        if (
            mots == "reprendre" or reprise_modification or reprise_confirmation
            or (sans_profil and mots in CHOIX_AVEC_PROFIL)
        ):
            parcours.statut = EN_COURS
            return question(parcours)

    if sans_profil and mots in CHOIX_AVEC_PROFIL and parcours is None:
        return onboarding.demarrer(session, conversation)

    if not sans_profil and mots == CHOIX_OBLIGATIONS:
        entreprise = session.get(Entreprise, conversation.entreprise_id)
        return obligations.voir_obligations(session, entreprise)

    if not sans_profil and mots == CHOIX_ECHEANCES:
        entreprise = session.get(Entreprise, conversation.entreprise_id)
        return echeances.voir_echeances(session, entreprise)

    if not sans_profil and mots == CHOIX_PROFIL:
        return profil.voir_profil(session.get(Entreprise, conversation.entreprise_id))

    if not sans_profil and mots in MODIFIER and parcours is None:
        return profil.demarrer(session, conversation, session.get(Entreprise, conversation.entreprise_id))

    if not sans_profil and mots in CONFIRMER and parcours is None:
        entreprise = session.get(Entreprise, conversation.entreprise_id)
        if profil.email_a_confirmer(entreprise):
            return confirmation.demarrer(session, conversation, entreprise)

    return repondre(texte)


def trouver_ou_creer_conversation(session: Session, canal: str, identifiant: str) -> Conversation:
    conversation = session.scalars(
        select(Conversation).where(
            Conversation.canal == canal, Conversation.identifiant_externe == identifiant
        )
    ).first()
    if conversation is None:
        conversation = Conversation(canal=canal, identifiant_externe=identifiant)
        session.add(conversation)
        session.flush()
    return conversation


def traiter_message(session: Session, canal: str, identifiant: str, texte: str) -> Reponse:
    """Enregistre le message entrant, calcule la réponse, enregistre la réponse."""
    if texte is None or not texte.strip():
        raise MessageVide("Le message est vide.")
    conversation = trouver_ou_creer_conversation(session, canal, identifiant)
    rappels = rappels_a_remettre(session, conversation)
    reponse = decider(session, conversation, texte)
    reponse.rappels = rappels
    session.add(Message(conversation_id=conversation.id, sens=ENTRANT, texte=texte[:LONGUEUR_MAX]))
    for rappel in rappels:
        session.add(Message(conversation_id=conversation.id, sens=SORTANT, texte=rappel))
    session.add(Message(conversation_id=conversation.id, sens=SORTANT, texte=reponse.texte))
    session.flush()
    return reponse


def historique(session: Session, canal: str, identifiant: str) -> list[Message]:
    """Messages d'une conversation, du plus ancien au plus récent ; vide si elle n'existe pas."""
    return list(
        session.scalars(
            select(Message)
            .join(Conversation)
            .where(Conversation.canal == canal, Conversation.identifiant_externe == identifiant)
            .order_by(Message.id)
        )
    )
