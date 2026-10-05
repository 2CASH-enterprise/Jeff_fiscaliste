"""Réception des notifications de Meta : chaque message écrit passe par le moteur commun.

Seuls les messages adressés au numéro de Jeff sont traités ; un message déjà reçu (Meta peut le
renvoyer) est ignoré ; les accusés de lecture et de remise sont ignorés.
"""
import hashlib
import hmac
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.conversation.models import CANAL_WHATSAPP, ENTRANT, SORTANT, Message
from app.conversation.moteur import LONGUEUR_MAX, traiter_message, trouver_ou_creer_conversation
from app.conversation.reponse import Reponse
from app.core.config import get_settings
from app.whatsapp.format import contenus
from app.whatsapp.models import A_ENVOYER, WhatsappEnvoi, WhatsappRecu


def signature_valide(corps: bytes, entete: str | None) -> bool:
    """Meta signe chaque notification avec le secret de l'application (en-tête X-Hub-Signature-256)."""
    secret = get_settings().whatsapp_secret_app
    if not entete or not entete.startswith("sha256=") or not secret:
        return False
    attendue = hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()
    return hmac.compare_digest(attendue, entete.removeprefix("sha256="))


def messages_recus(donnees: dict) -> list[dict]:
    """Les messages de la notification destinés au numéro de Jeff."""
    numero = get_settings().whatsapp_id_numero
    trouves = []
    if not isinstance(donnees, dict) or donnees.get("object") != "whatsapp_business_account":
        return trouves
    for entree in donnees.get("entry") or []:
        for changement in entree.get("changes") or []:
            valeur = changement.get("value") or {}
            if changement.get("field") != "messages" or (valeur.get("metadata") or {}).get("phone_number_id") != numero:
                continue
            trouves += [m for m in valeur.get("messages") or [] if m.get("id") and m.get("from")]
    return trouves


def texte_du_message(message: dict) -> str | None:
    """Le texte écrit, ou l'identifiant du bouton / de la ligne de liste choisi ; None pour le reste."""
    type_ = message.get("type")
    if type_ == "text":
        return (message.get("text") or {}).get("body") or None
    if type_ == "interactive":
        interactif = message.get("interactive") or {}
        reponse = interactif.get("button_reply") or interactif.get("list_reply") or {}
        return reponse.get("id") or None
    if type_ == "button":
        return (message.get("button") or {}).get("payload") or (message.get("button") or {}).get("text") or None
    return None


def deja_recu(session: Session, wamid: str, conversation_id) -> bool:
    resultat = session.execute(
        insert(WhatsappRecu)
        .values(wamid=wamid, conversation_id=conversation_id)
        .on_conflict_do_nothing(index_elements=["wamid"])
        .returning(WhatsappRecu.wamid)
    )
    return resultat.first() is None


def traiter_notification(session: Session, donnees: dict) -> list[int]:
    """Traite les messages reçus ; renvoie les identifiants des réponses à envoyer, dans l'ordre."""
    envois: list[WhatsappEnvoi] = []
    for message in messages_recus(donnees):
        numero = str(message["from"])[:32]
        conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero)
        if deja_recu(session, str(message["id"])[:200], conversation.id):
            continue
        texte = texte_du_message(message)
        if texte is None or not texte.strip():
            conversation.dernier_message_client_le = datetime.now(timezone.utc)
            reponse = Reponse(mf.WA_TYPE_NON_PRIS)
            session.add(Message(conversation_id=conversation.id, sens=ENTRANT, texte=f"[{message.get('type')}]"[:LONGUEUR_MAX]))
            session.add(Message(conversation_id=conversation.id, sens=SORTANT, texte=reponse.texte))
        else:
            reponse = traiter_message(session, CANAL_WHATSAPP, numero, texte)
        for contenu in contenus(reponse):
            envoi = WhatsappEnvoi(conversation_id=conversation.id, destinataire=numero, contenu=contenu, statut=A_ENVOYER, essais=0)
            session.add(envoi)
            envois.append(envoi)
    session.flush()
    return [e.id for e in envois]
