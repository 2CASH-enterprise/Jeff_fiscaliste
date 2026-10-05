"""Envoi des emails de la boîte d'envoi par SMTP (Brevo), avec 3 essais au plus.

Un rappel dont l'email échoue trois fois revient dans la bulle : le client ne le perd pas.
Le texte d'un email de code est effacé une fois envoyé (le code n'a plus à rester en base).
"""
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.emails.models import A_ENVOYER, CODE, ECHEC, ENVOYE, Email
from app.rappels import models as rappels
from app.rappels.canal import BULLE

ESSAIS_MAX = 3
LOT = 100
CODE_EFFACE = "[code effacé après envoi]"


@dataclass
class Bilan:
    envoyes: int = 0
    echecs: int = 0
    desactive: bool = False


def construire(destinataire: str, objet: str, texte: str, html: str) -> EmailMessage:
    reglages = get_settings()
    message = EmailMessage()
    message["From"] = formataddr((reglages.email_nom_expediteur, reglages.email_expediteur))
    message["To"] = destinataire
    message["Subject"] = objet
    message["Date"] = formatdate(localtime=False)
    message["Message-ID"] = make_msgid(domain=reglages.email_expediteur.split("@")[-1])
    message.set_content(texte)
    message.add_alternative(html, subtype="html")
    return message


def envoyer_smtp(destinataire: str, objet: str, texte: str, html: str) -> None:
    reglages = get_settings()
    message = construire(destinataire, objet, texte, html)
    with smtplib.SMTP(reglages.smtp_hote, reglages.smtp_port, timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(reglages.smtp_utilisateur, reglages.smtp_mot_de_passe)
        smtp.send_message(message)


def envoyer_un(session: Session, email: Email) -> bool:
    try:
        envoyer_smtp(email.destinataire, email.objet, email.texte, email.html)
    except Exception as erreur:  # Toute panne (réseau, refus du serveur) compte comme un essai raté.
        email.essais += 1
        email.erreur = f"{type(erreur).__name__}: {erreur}"[:500]
        if email.essais >= ESSAIS_MAX:
            email.statut = ECHEC
            if email.rappel_id is not None:
                rappel = session.get(rappels.Rappel, email.rappel_id)
                rappel.canal = BULLE
                rappel.statut = rappels.A_ENVOYER
        return False
    maintenant = datetime.now(timezone.utc)
    email.statut = ENVOYE
    email.envoye_le = maintenant
    email.erreur = None
    if email.type == CODE:
        email.texte = email.html = CODE_EFFACE
    if email.rappel_id is not None:
        rappel = session.get(rappels.Rappel, email.rappel_id)
        rappel.statut = rappels.ENVOYE
        rappel.envoye_le = maintenant
    return True


def envoyer_en_attente(session: Session) -> Bilan:
    """Envoie les emails en attente, un par un, en validant après chacun (rien n'est envoyé deux fois)."""
    if not get_settings().email_configure:
        return Bilan(desactive=True)
    bilan = Bilan()
    identifiants = list(session.scalars(
        select(Email.id).where(Email.statut == A_ENVOYER).order_by(Email.id).limit(LOT)
    ))
    for identifiant in identifiants:
        email = session.get(Email, identifiant, with_for_update={"skip_locked": True}, populate_existing=True)
        if email is None or email.statut != A_ENVOYER:
            session.commit()
            continue
        if envoyer_un(session, email):
            bilan.envoyes += 1
        else:
            bilan.echecs += 1
        session.commit()
    return bilan
