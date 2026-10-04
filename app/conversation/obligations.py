"""Réponse « Voir mes obligations » : liste construite par le code à partir du moteur de règles."""
from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.conversation.reponse import Reponse
from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction
from app.regles.conditions import INCERTAIN
from app.regles.models import A_VALIDER, OBLIGATION, PERIODICITES, Regle
from app.regles.moteur import evaluer_entreprise


def source(regle: Regle) -> str:
    parties = [p for p in (regle.source_texte, regle.source_article) if p]
    if parties:
        return ", ".join(parties)
    return regle.source_url or mf.SOURCE_A_COMPLETER


def bloc_obligation(regle: Regle) -> str:
    details = [PERIODICITES[regle.periodicite], mf.OBLIGATIONS_ECHEANCE.format(echeance=regle.echeance or mf.A_CONFIRMER)]
    return "\n".join([
        f"• {regle.titre}",
        "  " + " · ".join(details),
        "  " + mf.OBLIGATIONS_SOURCE.format(source=source(regle)),
    ])


def bloc_alerte(regle: Regle) -> str:
    return f"• {regle.titre} : {regle.description}"


def voir_obligations(session: Session, entreprise: Entreprise) -> Reponse:
    juridiction = session.get(Juridiction, entreprise.juridiction_code)
    resultats = evaluer_entreprise(session, entreprise, aujourd_hui(juridiction.fuseau_horaire))
    obligations = [r for r in resultats if r.regle.type == OBLIGATION and r.applicabilite != INCERTAIN]
    a_confirmer = [r for r in resultats if r.regle.type == OBLIGATION and r.applicabilite == INCERTAIN]
    alertes = [r for r in resultats if r.regle.type != OBLIGATION]

    if not obligations and not a_confirmer and not alertes:
        return Reponse(mf.OBLIGATIONS_AUCUNE, list(mf.MENU))

    parties = [mf.OBLIGATIONS_INTRO.format(raison_sociale=entreprise.raison_sociale)]
    if obligations:
        parties.append("\n\n".join(bloc_obligation(r.regle) for r in obligations))
    if a_confirmer:
        parties.append(mf.OBLIGATIONS_A_CONFIRMER + "\n" + "\n\n".join(bloc_obligation(r.regle) for r in a_confirmer))
    if alertes:
        parties.append(mf.OBLIGATIONS_ALERTES + "\n" + "\n".join(bloc_alerte(r.regle) for r in alertes))
    if any(r.regle.statut == A_VALIDER for r in resultats):
        parties.append(mf.OBLIGATIONS_AVERTISSEMENT)
    return Reponse("\n\n".join(parties), list(mf.MENU))
