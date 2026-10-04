"""Réponse « Voir mes échéances » : la prochaine échéance de chaque obligation, calculée par le code."""
from datetime import date

from sqlalchemy.orm import Session

from app.calendrier.dates import JOURS, formater_date, formater_delai, prochaine_echeance
from app.calendrier.feries import jour_ferie
from app.conversation import messages_fixes as mf
from app.conversation.reponse import Reponse
from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction
from app.regles.conditions import INCERTAIN
from app.regles.models import A_VALIDER, OBLIGATION, PERIODICITES, Regle
from app.regles.moteur import evaluer_entreprise

PONCTUELLE = "ponctuelle"


def avertissement(jour: date) -> str | None:
    """Jamais de report de date (décision du lot 5) : on prévient seulement."""
    nom = jour_ferie(jour)
    if nom:
        return mf.ECHEANCES_FERIE.format(nom=nom)
    if jour.weekday() >= 5:
        return mf.ECHEANCES_WEEK_END.format(jour=JOURS[jour.weekday()])
    return None


def bloc_date(regle: Regle, ce_jour: date) -> tuple[date, str]:
    echeance = prochaine_echeance(regle.echeance_calcul, ce_jour)
    lignes = [
        f"• {regle.titre} — {echeance.periode}",
        "  " + mf.ECHEANCES_LIGNE.format(
            date=formater_date(echeance.date_limite), delai=formater_delai(echeance.date_limite, ce_jour)
        ),
    ]
    alerte = avertissement(echeance.date_limite)
    if alerte:
        lignes.append("  " + alerte)
    return echeance.date_limite, "\n".join(lignes)


def ligne_simple(regle: Regle) -> str:
    if regle.periodicite == PONCTUELLE:
        return f"• {regle.titre}"
    return f"• {regle.titre} ({PERIODICITES[regle.periodicite].lower()})"


def voir_echeances(session: Session, entreprise: Entreprise) -> Reponse:
    juridiction = session.get(Juridiction, entreprise.juridiction_code)
    ce_jour = aujourd_hui(juridiction.fuseau_horaire)
    resultats = [r for r in evaluer_entreprise(session, entreprise, ce_jour) if r.regle.type == OBLIGATION]
    if not resultats:
        return Reponse(mf.ECHEANCES_AUCUNE, list(mf.MENU))

    certaines = [r.regle for r in resultats if r.applicabilite != INCERTAIN]
    datees = sorted(
        (bloc_date(regle, ce_jour) for regle in certaines if regle.echeance_calcul),
        key=lambda element: element[0],
    )
    sans_date = [r for r in certaines if not r.echeance_calcul and r.periodicite != PONCTUELLE]
    ponctuelles = [r for r in certaines if r.periodicite == PONCTUELLE]
    incertaines = [r.regle for r in resultats if r.applicabilite == INCERTAIN]

    parties = [mf.ECHEANCES_INTRO.format(raison_sociale=entreprise.raison_sociale)]
    if datees:
        parties.append("\n\n".join(texte for _, texte in datees))
    if sans_date:
        parties.append(mf.ECHEANCES_SANS_DATE + "\n" + "\n".join(ligne_simple(r) for r in sans_date))
    if ponctuelles:
        parties.append(mf.ECHEANCES_PONCTUELLES + "\n" + "\n".join(ligne_simple(r) for r in ponctuelles))
    if incertaines:
        parties.append(mf.ECHEANCES_A_CONFIRMER + "\n" + "\n".join(ligne_simple(r) for r in incertaines))
    if any(r.regle.statut == A_VALIDER for r in resultats):
        parties.append(mf.OBLIGATIONS_AVERTISSEMENT)
    return Reponse("\n\n".join(parties), list(mf.MENU))
