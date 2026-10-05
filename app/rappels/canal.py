"""Routeur de canal : choisit par où un rappel est remis au client.

Décisions des lots 8 et 10 :
- conversation WhatsApp ouverte depuis moins de 24 h → WhatsApp, message libre (gratuit) ;
- sinon, rappel prioritaire (J-2) et moins de 5 messages prioritaires ce mois-ci → WhatsApp, modèle Meta ;
- sinon → email si l'adresse est confirmée, sinon la bulle (repli).
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.conversation.models import CANAL_WHATSAPP, Conversation
from app.core.config import get_settings
from app.entreprises.models import Entreprise

BULLE = "bulle"
EMAIL = "email"
WHATSAPP = "whatsapp"
CANAUX = (BULLE, EMAIL, WHATSAPP)

PALIERS_PRIORITAIRES = {2}
PLAFOND_MENSUEL = 5


@dataclass
class Choix:
    canal: str
    conversation: Conversation | None = None
    modele: str | None = None  # Nom du modèle Meta quand la fenêtre de 24 h est fermée.


def canal_de_repli(entreprise: Entreprise) -> str:
    if entreprise.email and entreprise.email_confirme_le is not None:
        return EMAIL
    return BULLE


def choisir_canal(entreprise: Entreprise) -> str:
    """Canal sans WhatsApp (lot 8), gardé pour les appels existants."""
    return canal_de_repli(entreprise)


def conversation_whatsapp(session: Session, entreprise: Entreprise) -> Conversation | None:
    """La conversation WhatsApp de l'entreprise la plus récemment active."""
    return session.scalars(
        select(Conversation)
        .where(
            Conversation.entreprise_id == entreprise.id,
            Conversation.canal == CANAL_WHATSAPP,
            Conversation.rappels_whatsapp.is_(True),
        )
        .order_by(Conversation.dernier_message_client_le.desc().nulls_last(), Conversation.cree_le.desc())
    ).first()


def debut_du_mois(maintenant: datetime, fuseau: str) -> datetime:
    local = maintenant.astimezone(ZoneInfo(fuseau))
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def prioritaires_du_mois(session: Session, entreprise: Entreprise, maintenant: datetime, fuseau: str) -> int:
    """Messages WhatsApp par modèle déjà envoyés ou en cours ce mois-ci (les échecs ne comptent pas)."""
    from app.whatsapp.models import A_ENVOYER, ENVOYE, WhatsappEnvoi

    return session.scalar(
        select(func.count()).select_from(WhatsappEnvoi).where(
            WhatsappEnvoi.entreprise_id == entreprise.id,
            WhatsappEnvoi.modele.is_not(None),
            WhatsappEnvoi.statut.in_((A_ENVOYER, ENVOYE)),
            WhatsappEnvoi.cree_le >= debut_du_mois(maintenant, fuseau),
        )
    )


def choisir(session: Session, entreprise: Entreprise, palier: int, maintenant: datetime | None = None,
            fuseau: str = "Africa/Douala") -> Choix:
    from app.conversation.moteur import fenetre_ouverte

    maintenant = maintenant or datetime.now(timezone.utc)
    reglages = get_settings()
    conversation = conversation_whatsapp(session, entreprise) if reglages.whatsapp_configure else None
    if conversation is not None:
        if fenetre_ouverte(conversation, maintenant):
            return Choix(WHATSAPP, conversation)
        if (
            palier in PALIERS_PRIORITAIRES
            and reglages.whatsapp_modele_rappel
            and prioritaires_du_mois(session, entreprise, maintenant, fuseau) < PLAFOND_MENSUEL
        ):
            return Choix(WHATSAPP, conversation, reglages.whatsapp_modele_rappel)
    return Choix(canal_de_repli(entreprise))
