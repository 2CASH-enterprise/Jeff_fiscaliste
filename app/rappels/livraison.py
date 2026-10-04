"""Remise des rappels dans la bulle : affichés avant la réponse au prochain message du client."""
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendrier.dates import formater_date, formater_delai
from app.conversation import messages_fixes as mf
from app.conversation.echeances import avertissement
from app.conversation.models import Conversation
from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.rappels.canal import BULLE
from app.rappels.models import A_ENVOYER, ENVOYE, EXPIRE, Rappel
from app.referentiel.models import Juridiction
from app.regles.models import A_VALIDER, Regle


def texte_rappel(rappel: Rappel, regle: Regle, ce_jour: date) -> str:
    lignes = [
        mf.RAPPEL.format(titre=regle.titre, periode=rappel.periode),
        mf.ECHEANCES_LIGNE.format(
            date=formater_date(rappel.date_limite), delai=formater_delai(rappel.date_limite, ce_jour)
        ) + ".",
    ]
    alerte = avertissement(rappel.date_limite)
    if alerte:
        lignes.append(alerte)
    if regle.statut == A_VALIDER:
        lignes.append(mf.OBLIGATIONS_AVERTISSEMENT)
    return "\n".join(lignes)


def rappels_a_remettre(session: Session, conversation: Conversation) -> list[str]:
    """Textes des rappels en attente pour l'entreprise de la conversation ; ils passent en « envoyé »."""
    if conversation.entreprise_id is None:
        return []
    entreprise = session.get(Entreprise, conversation.entreprise_id)
    ce_jour = aujourd_hui(session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire)
    rappels = session.scalars(
        select(Rappel)
        .where(Rappel.entreprise_id == entreprise.id, Rappel.statut == A_ENVOYER, Rappel.canal == BULLE)
        .order_by(Rappel.date_limite, Rappel.id)
        .with_for_update(skip_locked=True)
    )
    textes = []
    for rappel in rappels:
        if rappel.date_limite < ce_jour:
            rappel.statut = EXPIRE
            continue
        textes.append(texte_rappel(rappel, session.get(Regle, rappel.regle_id), ce_jour))
        rappel.statut = ENVOYE
        rappel.conversation_id = conversation.id
        rappel.envoye_le = datetime.now(timezone.utc)
    session.flush()
    return textes
