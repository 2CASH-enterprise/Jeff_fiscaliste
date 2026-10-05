"""Repli d'un rappel dont le message WhatsApp a échoué : email si l'adresse est confirmée, sinon bulle."""
from sqlalchemy.orm import Session

from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.rappels.canal import EMAIL, canal_de_repli
from app.rappels.models import A_ENVOYER, Rappel
from app.referentiel.models import Juridiction
from app.regles.models import Regle


def replier(session: Session, rappel: Rappel) -> str:
    from app.emails.composition import email_rappel

    entreprise = session.get(Entreprise, rappel.entreprise_id)
    rappel.canal = canal_de_repli(entreprise)
    rappel.statut = A_ENVOYER
    rappel.conversation_id = None
    rappel.envoye_le = None
    if rappel.canal == EMAIL:
        ce_jour = aujourd_hui(session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire)
        email_rappel(session, entreprise, rappel, session.get(Regle, rappel.regle_id), ce_jour)
    session.flush()
    return rappel.canal
