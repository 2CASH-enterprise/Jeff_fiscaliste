"""Données affichées par le coffre fiscal (lot 12) : accueil et fiche de l'entreprise.

Mêmes calculs que la conversation (« Voir mes échéances », « Mon entreprise ») : le coffre
n'invente rien, il présente autrement ce que Jeff sait déjà.
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendrier.dates import formater_date, prochaine_echeance
from app.conversation import messages_fixes as mf
from app.conversation import onboarding
from app.conversation.echeances import PONCTUELLE, avertissement
from app.conversation.models import CANAL_WHATSAPP, Conversation
from app.conversation.profil import donnees_depuis_entreprise
from app.core.temps import aujourd_hui
from app.entreprises.models import Entreprise
from app.referentiel.models import Juridiction
from app.regles.conditions import INCERTAIN
from app.regles.models import A_VALIDER, OBLIGATION
from app.regles.moteur import evaluer_entreprise

A_VENIR_MAX = 4
MOIS_COURTS = ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
CHIFFRES_VISIBLES = 4  # Numéro WhatsApp : seuls les derniers chiffres sont montrés.


@dataclass
class Echeance:
    titre: str
    periode: str
    date_limite: date
    date_texte: str
    mois_court: str
    jours: int
    alerte: str | None


@dataclass
class Tableau:
    prochaine: Echeance | None
    a_venir: list[Echeance] = field(default_factory=list)
    a_confirmer: list[str] = field(default_factory=list)
    sans_date: list[str] = field(default_factory=list)
    nombre_obligations: int = 0
    a_valider: bool = False


def ce_jour(session: Session, entreprise: Entreprise) -> date:
    return aujourd_hui(session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire)


def tableau(session: Session, entreprise: Entreprise, jour: date | None = None) -> Tableau:
    jour = jour or ce_jour(session, entreprise)
    resultats = [r for r in evaluer_entreprise(session, entreprise, jour) if r.regle.type == OBLIGATION]
    certaines = [r.regle for r in resultats if r.applicabilite != INCERTAIN]
    datees = []
    for regle in certaines:
        if regle.echeance_calcul:
            echeance = prochaine_echeance(regle.echeance_calcul, jour)
            datees.append(Echeance(
                titre=regle.titre,
                periode=echeance.periode,
                date_limite=echeance.date_limite,
                date_texte=formater_date(echeance.date_limite),
                mois_court=MOIS_COURTS[echeance.date_limite.month - 1],
                jours=(echeance.date_limite - jour).days,
                alerte=avertissement(echeance.date_limite),
            ))
    datees.sort(key=lambda e: (e.date_limite, e.titre))
    return Tableau(
        prochaine=datees[0] if datees else None,
        a_venir=datees[1:1 + A_VENIR_MAX],
        a_confirmer=[r.regle.titre for r in resultats if r.applicabilite == INCERTAIN],
        sans_date=[r.titre for r in certaines if not r.echeance_calcul and r.periodicite != PONCTUELLE],
        nombre_obligations=len(resultats),
        a_valider=any(r.regle.statut == A_VALIDER for r in resultats),
    )


@dataclass
class Fiche:
    lignes: list[tuple[str, str, bool]]  # libellé, valeur, verrouillée
    email: str | None
    whatsapp: list[tuple[str, bool]]  # numéro masqué, rappels actifs


def masquer(numero: str) -> str:
    return "•••• " + numero[-CHIFFRES_VISIBLES:]


def valeur_affichee(cle: str, valeur) -> str:
    """Comme dans la conversation ; une information jamais donnée s'affiche « À compléter »."""
    return mf.A_COMPLETER if valeur is None else onboarding.afficher(cle, valeur)


def fiche(session: Session, entreprise: Entreprise) -> Fiche:
    donnees = donnees_depuis_entreprise(entreprise)
    lignes = [
        (e.libelle, valeur_affichee(e.cle, donnees.get(e.cle)), e.cle == "niu")
        for e in onboarding.etapes_visibles(donnees)
        if e.cle != "email"
    ]
    conversations = session.scalars(
        select(Conversation)
        .where(Conversation.entreprise_id == entreprise.id, Conversation.canal == CANAL_WHATSAPP)
        .order_by(Conversation.cree_le)
    )
    return Fiche(
        lignes=lignes,
        email=entreprise.email,
        whatsapp=[(masquer(c.identifiant_externe), c.rappels_whatsapp) for c in conversations],
    )
