"""Moteur conversationnel commun à tous les canaux (bulle web, WhatsApp plus tard).

Il reçoit un texte, enregistre l'échange et renvoie une réponse. Pour l'instant, les réponses
sont des messages fixes ; l'IA viendra plus tard sans changer cette interface.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.conversation.models import ENTRANT, SORTANT, Conversation, Message

LONGUEUR_MAX = 2000

SALUTATIONS = {"bonjour", "bonsoir", "salut", "hello", "coucou", "bjr", "slt", "menu"}


@dataclass
class Reponse:
    texte: str
    choix: list[tuple[str, str]] = field(default_factory=list)


class MessageVide(ValueError):
    pass


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces réduits."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", sans_accents.lower())).strip()


def repondre(texte: str) -> Reponse:
    """Décide de la réponse, sans effet de bord."""
    if len(texte) > LONGUEUR_MAX:
        return Reponse(mf.TROP_LONG)
    mots = normaliser(texte)
    premier_mot = mots.split()[0] if mots else ""
    if premier_mot in SALUTATIONS:
        return Reponse(mf.ACCUEIL, list(mf.MENU))
    for valeur, libelle in mf.MENU:
        if mots == valeur:
            return Reponse(mf.BIENTOT.format(libelle=libelle))
    return Reponse(mf.INCOMPRIS)


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
    reponse = repondre(texte)
    session.add(Message(conversation_id=conversation.id, sens=ENTRANT, texte=texte[:LONGUEUR_MAX]))
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
