"""Préférences de rappels (lot 14) : rappels WhatsApp par numéro, rappels par email par entreprise.

Un canal coupé l'est aussitôt : les rappels qui attendaient d'y partir sont annulés sur ce canal
et repliés (email si possible, sinon la bulle). Chaque changement est tracé avec son origine.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation.models import Conversation
from app.emails import models as emails
from app.entreprises.models import CONVERSATION, Entreprise, ModificationEntreprise
from app.rappels.models import Rappel
from app.rappels.repli import replier

RAPPELS_WHATSAPP = "rappels_whatsapp"
RAPPELS_EMAIL = "rappels_email"


def tracer(session: Session, entreprise_id, champ: str, ancienne, nouvelle, origine: str,
           conversation_id=None, session_espace_id=None) -> None:
    session.add(ModificationEntreprise(
        entreprise_id=entreprise_id,
        conversation_id=conversation_id,
        champ=champ,
        ancienne_valeur=ancienne,
        nouvelle_valeur=nouvelle,
        origine=origine,
        session_espace_id=session_espace_id,
    ))


def changer_rappels_whatsapp(session: Session, conversation: Conversation, actifs: bool,
                             origine: str = CONVERSATION, session_espace_id=None) -> bool:
    from app.whatsapp import models as whatsapp

    if conversation.rappels_whatsapp == actifs:
        return False
    conversation.rappels_whatsapp = actifs
    if not actifs:
        en_attente = session.scalars(select(whatsapp.WhatsappEnvoi).where(
            whatsapp.WhatsappEnvoi.conversation_id == conversation.id,
            whatsapp.WhatsappEnvoi.rappel_id.is_not(None),
            whatsapp.WhatsappEnvoi.statut == whatsapp.A_ENVOYER,
        ))
        for envoi in list(en_attente):
            envoi.statut = whatsapp.ANNULE
            replier(session, session.get(Rappel, envoi.rappel_id))
    if conversation.entreprise_id is not None:
        tracer(session, conversation.entreprise_id, RAPPELS_WHATSAPP, not actifs, actifs, origine,
               conversation.id, session_espace_id)
    session.flush()
    return True


def changer_rappels_email(session: Session, entreprise: Entreprise, actifs: bool,
                          origine: str, session_espace_id=None) -> bool:
    if entreprise.rappels_email == actifs:
        return False
    entreprise.rappels_email = actifs
    if not actifs:
        en_attente = session.scalars(select(emails.Email).where(
            emails.Email.entreprise_id == entreprise.id,
            emails.Email.type == emails.RAPPEL,
            emails.Email.statut == emails.A_ENVOYER,
        ))
        for email in list(en_attente):
            email.statut = emails.ANNULE
            replier(session, session.get(Rappel, email.rappel_id))
    tracer(session, entreprise.id, RAPPELS_EMAIL, not actifs, actifs, origine, session_espace_id=session_espace_id)
    session.flush()
    return True
