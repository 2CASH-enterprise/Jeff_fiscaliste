"""Envoi des messages WhatsApp par l'API Cloud de Meta, avec 3 essais au plus.

Chaque message est d'abord écrit dans la boîte d'envoi, puis envoyé tout de suite ; s'il échoue,
la tâche de la minute suivante le retente. Le jeton n'apparaît jamais dans les erreurs enregistrées.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.rappels.canal import WHATSAPP
from app.rappels.models import A_ENVOYER as A_ENVOYER_RAPPEL
from app.rappels.models import ENVOYE as ENVOYE_RAPPEL
from app.rappels.models import Rappel
from app.rappels.repli import replier
from app.whatsapp.models import A_ENVOYER, ECHEC, ENVOYE, WhatsappEnvoi

ESSAIS_MAX = 3
DELAI_REPRISE = timedelta(seconds=30)
LOT = 100


@dataclass
class Bilan:
    envoyes: int = 0
    echecs: int = 0
    desactive: bool = False


class ErreurMeta(Exception):
    def __init__(self, message: str, code_http: int = 0):
        super().__init__(message)
        self.code_http = code_http

    @property
    def definitive(self) -> bool:
        """Refus de Meta (modèle inconnu, numéro hors fenêtre…) : inutile de réessayer. 429 = trop d'envois."""
        return 400 <= self.code_http < 500 and self.code_http != 429


def url_messages() -> str:
    reglages = get_settings()
    return f"https://graph.facebook.com/{reglages.whatsapp_version_api}/{reglages.whatsapp_id_numero}/messages"


def envoyer_graph(destinataire: str, contenu: dict) -> str:
    """Envoie un message ; renvoie l'identifiant donné par Meta."""
    reglages = get_settings()
    corps = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": destinataire, **contenu}
    reponse = httpx.post(
        url_messages(), json=corps, headers={"Authorization": f"Bearer {reglages.whatsapp_jeton}"}, timeout=15
    )
    if reponse.status_code >= 400:
        try:
            erreur = reponse.json().get("error", {})
            detail = f"{erreur.get('code')} {erreur.get('message')}"
        except ValueError:
            detail = reponse.text[:200]
        raise ErreurMeta(f"HTTP {reponse.status_code} : {detail}", reponse.status_code)
    return reponse.json()["messages"][0]["id"]


def envoyer_un(session: Session, identifiant: int) -> bool | None:
    """Envoie un message de la boîte d'envoi s'il est toujours à envoyer (verrou : jamais deux fois)."""
    envoi = session.get(WhatsappEnvoi, identifiant, with_for_update={"skip_locked": True}, populate_existing=True)
    if envoi is None or envoi.statut != A_ENVOYER:
        session.commit()
        return None
    try:
        envoi.wamid = envoyer_graph(envoi.destinataire, envoi.contenu)
    except Exception as erreur:
        envoi.essais += 1
        envoi.erreur = f"{type(erreur).__name__}: {erreur}"[:500].replace(get_settings().whatsapp_jeton or "\0", "***")
        if envoi.essais >= ESSAIS_MAX or (isinstance(erreur, ErreurMeta) and erreur.definitive):
            marquer_echec(session, envoi)
        session.commit()
        return False
    envoi.statut = ENVOYE
    envoi.envoye_le = datetime.now(timezone.utc)
    envoi.erreur = None
    if envoi.rappel_id is not None:
        rappel = session.get(Rappel, envoi.rappel_id)
        if rappel.statut == A_ENVOYER_RAPPEL:
            rappel.statut = ENVOYE_RAPPEL
            rappel.envoye_le = envoi.envoye_le
    session.commit()
    return True


def marquer_echec(session: Session, envoi: WhatsappEnvoi) -> None:
    """Échec définitif : le rappel concerné repart par email ou dans la bulle."""
    envoi.statut = ECHEC
    if envoi.rappel_id is not None:
        rappel = session.get(Rappel, envoi.rappel_id)
        if rappel.canal == WHATSAPP:
            replier(session, rappel)


def envoyer_en_attente(session: Session) -> Bilan:
    """Reprise par la tâche de la minute : messages restés en attente (panne réseau, Meta indisponible)."""
    if not get_settings().whatsapp_configure:
        return Bilan(desactive=True)
    limite = datetime.now(timezone.utc) - DELAI_REPRISE
    identifiants = list(session.scalars(
        select(WhatsappEnvoi.id)
        .where(WhatsappEnvoi.statut == A_ENVOYER, WhatsappEnvoi.cree_le < limite)
        .order_by(WhatsappEnvoi.id)
        .limit(LOT)
    ))
    bilan = Bilan()
    for identifiant in identifiants:
        resultat = envoyer_un(session, identifiant)
        if resultat:
            bilan.envoyes += 1
        elif resultat is False:
            bilan.echecs += 1
    return bilan
