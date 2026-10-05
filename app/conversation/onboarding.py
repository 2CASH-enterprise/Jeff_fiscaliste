"""Parcours d'onboarding : 9 questions pour connaître l'entreprise, récapitulatif, enregistrement.

Toutes les décisions (validation des réponses, enchaînement des étapes, enregistrement) sont
prises ici par le code. Les textes viennent de messages_fixes.
"""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.conversation import confirmation
from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, EN_COURS, EN_PAUSE, TERMINE, Conversation, Parcours
from app.conversation.montants import (
    LectureImpossible,
    formater_montant,
    lire_montant,
    lire_nombre_entier,
)
from app.conversation.normalisation import normaliser
from app.conversation.reponse import Reponse
from app.core.config import get_settings
from app.entreprises.models import Entreprise
from app.entreprises.niu import NiuInvalide, normaliser_niu

TYPE = "onboarding"
MODIFICATION = "modification"  # Parcours de modification du profil (lot 6), même mécanique.
PROPOSITION = "proposition"
RECAPITULATIF = "recapitulatif"
CORRECTION = "correction"
RETOUR_RECAP = "_retour_recap"

SALARIES_MAX = 100_000
OUI = {"oui", "o", "ok", "d accord", "daccord", "oui commencons", "commencons", "go", "yes"}
PLUS_TARD = {"plus tard", "non", "pas maintenant", "later", "n"}
CORRIGER = {"corriger", "modifier", "non"}
INCONNU = "inconnu"


class ReponseInvalide(ValueError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# --- Lecteurs de réponses -----------------------------------------------------------------

def lire_texte(minimum: int, maximum: int) -> Callable[[str, Session], str]:
    def lire(texte: str, session: Session) -> str:
        valeur = re.sub(r"\s+", " ", texte).strip()
        if len(valeur) < minimum:
            raise ReponseInvalide(mf.ERR_TEXTE_COURT)
        if len(valeur) > maximum:
            raise ReponseInvalide(mf.ERR_TEXTE_LONG)
        return valeur

    return lire


def lire_niu(texte: str, session: Session) -> str:
    try:
        niu = normaliser_niu(texte)
    except NiuInvalide:
        raise ReponseInvalide(mf.ERR_NIU)
    if niu_deja_connu(session, niu):
        raise ReponseInvalide(mf.NIU_DEJA_CONNU)
    return niu


def niu_deja_connu(session: Session, niu: str) -> bool:
    return (
        session.scalars(
            select(Entreprise.id).where(
                Entreprise.juridiction_code == get_settings().juridiction, Entreprise.niu == niu
            )
        ).first()
        is not None
    )


def lire_choix(options: tuple[tuple[str, str, tuple[str, ...]], ...]) -> Callable[[str, Session], str]:
    """Accepte le numéro du bouton, son libellé, ou un synonyme ; renvoie le code stocké."""

    def lire(texte: str, session: Session) -> str:
        mots = normaliser(texte)
        for numero, (code, libelle, synonymes) in enumerate(options, start=1):
            if mots in {str(numero), normaliser(libelle), *synonymes}:
                return code
        raise ReponseInvalide(mf.ERR_CHOIX)

    return lire


def lire_chiffre_affaires(texte: str, session: Session) -> int:
    try:
        return lire_montant(texte)
    except LectureImpossible:
        raise ReponseInvalide(mf.ERR_MONTANT)


def lire_salaries(texte: str, session: Session) -> int:
    try:
        return lire_nombre_entier(texte, SALARIES_MAX)
    except LectureImpossible:
        raise ReponseInvalide(mf.ERR_NOMBRE)


def lire_cnps(texte: str, session: Session) -> str | None:
    mots = normaliser(texte)
    if mots in {"plus tard", "je ne sais pas", "je ne l ai pas", "inconnu"}:
        return None
    numero = re.sub(r"[\s\-/.]", "", texte).upper()
    if not numero.isalnum() or not 3 <= len(numero) <= 30:
        raise ReponseInvalide(mf.ERR_CNPS)
    return numero


EMAIL_MAX = 254
SANS_EMAIL = {"plus tard", "je la donnerai plus tard", "aucune", "aucun", "supprimer", "pas d email", "je n en ai pas"}


def lire_email(texte: str, session: Session) -> str | None:
    if normaliser(texte) in SANS_EMAIL:
        return None
    email = texte.strip().lower()
    if len(email) > EMAIL_MAX or not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)*\.[a-z]{2,}", email):
        raise ReponseInvalide(mf.ERR_EMAIL)
    if ".." in email:
        raise ReponseInvalide(mf.ERR_EMAIL)
    return email


# --- Les questions ------------------------------------------------------------------------

FORMES = (
    ("entreprise_individuelle", "Entreprise individuelle", ("ei", "individuelle", "ets", "etablissement")),
    ("sarl", "SARL", ()),
    ("sarlu", "SARL unipersonnelle", ("sarlu",)),
    ("sa", "SA", ()),
    ("sas", "SAS", ("sasu",)),
    ("autre", "Autre", ()),
)
SECTEURS = (
    ("commerce", "Commerce", ("negoce", "vente")),
    ("services", "Services", ("service", "prestations", "prestation de services")),
    ("industrie_btp", "Industrie et BTP", ("industrie", "btp", "construction")),
    ("agriculture", "Agriculture", ("agricole", "elevage", "peche")),
    ("autre", "Autre", ()),
)
REGIMES = (
    ("liberatoire", "Impôt libératoire", ("liberatoire", "il")),
    ("simplifie", "Régime simplifié", ("simplifie", "rsi")),
    ("reel", "Régime du réel", ("reel", "regime reel")),
    (INCONNU, mf.NE_SAIS_PAS, ("je sais pas", "ne sais pas", "inconnu", "nsp", "aucune idee")),
)
TVA = (
    ("oui", "Oui", ("o", "yes")),
    ("non", "Non", ("n", "no")),
    (INCONNU, mf.NE_SAIS_PAS, ("je sais pas", "ne sais pas", "inconnu", "nsp")),
)


def boutons(options) -> list[tuple[str, str]]:
    return [(str(numero), libelle) for numero, (_, libelle, _) in enumerate(options, start=1)]


@dataclass
class Etape:
    cle: str
    libelle: str
    question: str
    lire: Callable[[str, Session], Any]
    choix: list[tuple[str, str]] = field(default_factory=list)
    condition: Callable[[dict], bool] = lambda donnees: True


ETAPES = (
    Etape("raison_sociale", "Raison sociale", mf.Q_RAISON_SOCIALE, lire_texte(2, 200)),
    Etape("niu", "NIU", mf.Q_NIU, lire_niu),
    Etape("forme_juridique", "Forme juridique", mf.Q_FORME_JURIDIQUE, lire_choix(FORMES), boutons(FORMES)),
    Etape("secteur", "Secteur", mf.Q_SECTEUR, lire_choix(SECTEURS), boutons(SECTEURS)),
    Etape("chiffre_affaires_annuel", "Chiffre d'affaires annuel", mf.Q_CHIFFRE_AFFAIRES, lire_chiffre_affaires),
    Etape("centre_impots", "Centre des impôts", mf.Q_CENTRE_IMPOTS, lire_texte(2, 100)),
    Etape("regime_declare", "Régime d'imposition", mf.Q_REGIME, lire_choix(REGIMES), boutons(REGIMES)),
    Etape("assujetti_tva_declare", "Assujetti à la TVA", mf.Q_TVA, lire_choix(TVA), boutons(TVA)),
    Etape("nombre_salaries", "Nombre de salariés", mf.Q_SALARIES, lire_salaries),
    Etape(
        "numero_employeur_cnps",
        "N° employeur CNPS",
        mf.Q_CNPS,
        lire_cnps,
        [("plus tard", "Je le donnerai plus tard")],
        condition=lambda donnees: (donnees.get("nombre_salaries") or 0) > 0,
    ),
    Etape("email", "Adresse email", mf.Q_EMAIL, lire_email, list(mf.CHOIX_EMAIL)),
)
PAR_CLE = {etape.cle: etape for etape in ETAPES}


# --- Affichage ----------------------------------------------------------------------------

def libelle_option(options, code) -> str:
    return next((libelle for c, libelle, _ in options if c == code), str(code))


def afficher(cle: str, valeur: Any) -> str:
    if cle in ("numero_employeur_cnps", "email") and valeur is None:
        return mf.A_COMPLETER
    if cle == "chiffre_affaires_annuel":
        return formater_montant(valeur)
    if cle == "forme_juridique":
        return libelle_option(FORMES, valeur)
    if cle == "secteur":
        return libelle_option(SECTEURS, valeur)
    if cle == "regime_declare":
        return libelle_option(REGIMES, valeur)
    if cle == "assujetti_tva_declare":
        return libelle_option(TVA, valeur)
    return str(valeur)


def etapes_visibles(donnees: dict) -> list[Etape]:
    return [etape for etape in ETAPES if etape.condition(donnees)]


def lignes_profil(donnees: dict, niu_verrouille: bool = False) -> list[str]:
    lignes = []
    for e in etapes_visibles(donnees):
        ligne = f"• {e.libelle} : {afficher(e.cle, donnees.get(e.cle))}"
        if niu_verrouille and e.cle == "niu":
            ligne += f" ({mf.NON_MODIFIABLE})"
        lignes.append(ligne)
    return lignes


def recapitulatif(donnees: dict, type_parcours: str = TYPE) -> Reponse:
    if type_parcours == MODIFICATION:
        lignes = lignes_profil(donnees, niu_verrouille=True)
        texte = "\n".join([mf.MODIFICATION_RECAP_INTRO, *lignes, "", mf.MODIFICATION_RECAP_QUESTION])
        return Reponse(texte, list(mf.CHOIX_RECAP_MODIFICATION))
    texte = "\n".join([mf.RECAP_INTRO, *lignes_profil(donnees), "", mf.RECAP_QUESTION])
    return Reponse(texte, list(mf.CHOIX_RECAP))


def question(parcours: Parcours) -> Reponse:
    """Repose la question de l'étape courante."""
    if parcours.etape == PROPOSITION:
        return Reponse(mf.PROPOSITION_ONBOARDING, list(mf.CHOIX_PROPOSITION))
    if parcours.etape == RECAPITULATIF:
        return recapitulatif(parcours.donnees, parcours.type)
    if parcours.etape == CORRECTION:
        return menu_correction(parcours)
    etape = PAR_CLE[parcours.etape]
    return Reponse(etape.question, list(etape.choix))


def corrigeables(parcours: Parcours) -> list[Etape]:
    """Étapes proposées à la correction ; le NIU est verrouillé une fois le profil créé."""
    visibles = etapes_visibles(parcours.donnees)
    if parcours.type == MODIFICATION:
        return [e for e in visibles if e.cle != "niu"]
    return visibles


def menu_correction(parcours: Parcours) -> Reponse:
    choix = [(str(numero), e.libelle) for numero, e in enumerate(corrigeables(parcours), start=1)]
    texte = mf.MODIFICATION_QUELLE if parcours.type == MODIFICATION else mf.CORRECTION
    return Reponse(texte, choix)


# --- Enchaînement -------------------------------------------------------------------------

def demarrer(session: Session, conversation: Conversation) -> Reponse:
    parcours = Parcours(conversation_id=conversation.id, type=TYPE, etape=PROPOSITION, donnees={})
    session.add(parcours)
    session.flush()
    return question(parcours)


def etape_suivante(cle: str, donnees: dict) -> str:
    if donnees.get(RETOUR_RECAP):
        # Après une correction : seule une nouvelle question conditionnelle peut s'intercaler.
        cnps = PAR_CLE["numero_employeur_cnps"]
        if cle == "nombre_salaries" and cnps.condition(donnees) and cnps.cle not in donnees:
            return cnps.cle
        return RECAPITULATIF
    cles = [e.cle for e in ETAPES]
    for etape in ETAPES[cles.index(cle) + 1:]:
        if etape.condition(donnees):
            return etape.cle
    return RECAPITULATIF


def avancer(session: Session, conversation: Conversation, parcours: Parcours, texte: str) -> Reponse:
    mots = normaliser(texte)

    if parcours.etape == PROPOSITION:
        if mots in OUI:
            parcours.etape = ETAPES[0].cle
            return question(parcours)
        if mots in PLUS_TARD:
            parcours.statut = ABANDONNE
            return Reponse(mf.PLUS_TARD, list(mf.MENU))
        return Reponse(mf.ERR_CHOIX, list(mf.CHOIX_PROPOSITION))

    if parcours.etape == RECAPITULATIF:
        if mots in OUI:
            return finaliser(session, conversation, parcours)
        if mots in CORRIGER:
            parcours.etape = CORRECTION
            return question(parcours)
        return Reponse(mf.ERR_CHOIX, list(mf.CHOIX_RECAP))

    if parcours.etape == CORRECTION:
        proposees = corrigeables(parcours)
        if mots.isdigit() and 1 <= int(mots) <= len(proposees):
            parcours.donnees = {**parcours.donnees, RETOUR_RECAP: True}
            parcours.etape = proposees[int(mots) - 1].cle
            return question(parcours)
        return Reponse(mf.ERR_CHOIX, menu_correction(parcours).choix)

    etape = PAR_CLE[parcours.etape]
    try:
        valeur = etape.lire(texte, session)
    except ReponseInvalide as erreur:
        return Reponse(erreur.message, list(etape.choix))

    donnees = {**parcours.donnees, etape.cle: valeur}
    if etape.cle == "nombre_salaries" and not PAR_CLE["numero_employeur_cnps"].condition(donnees):
        donnees.pop("numero_employeur_cnps", None)
    parcours.donnees = donnees
    parcours.etape = etape_suivante(etape.cle, donnees)
    return question(parcours)


def finaliser(session: Session, conversation: Conversation, parcours: Parcours) -> Reponse:
    donnees = parcours.donnees
    if niu_deja_connu(session, donnees["niu"]):
        # Enregistré entre-temps par quelqu'un d'autre : on redemande le NIU.
        parcours.donnees = {**donnees, RETOUR_RECAP: True}
        parcours.etape = "niu"
        return Reponse(mf.NIU_DEJA_CONNU)
    entreprise = Entreprise(
        juridiction_code=get_settings().juridiction,
        niu=donnees["niu"],
        **colonnes(donnees),
        numero_employeur_cnps=donnees.get("numero_employeur_cnps"),
    )
    session.add(entreprise)
    session.flush()
    conversation.entreprise_id = entreprise.id
    parcours.statut = TERMINE
    bienvenue = mf.BIENVENUE.format(raison_sociale=entreprise.raison_sociale)
    if entreprise.email:
        session.flush()  # L'onboarding est clos avant d'ouvrir la confirmation (un seul parcours actif).
        code = confirmation.demarrer(session, conversation, entreprise)
        return Reponse(bienvenue + "\n\n" + code.texte, code.choix)
    return Reponse(bienvenue, list(mf.MENU))


# Champs du profil modifiables après la création (le NIU ne l'est pas).
CHAMPS_MODIFIABLES = (
    "raison_sociale", "forme_juridique", "secteur", "chiffre_affaires_annuel", "centre_impots",
    "regime_declare", "assujetti_tva_declare", "nombre_salaries", "email",
)


def colonnes(donnees: dict) -> dict:
    """Réponses du questionnaire → valeurs des colonnes de l'entreprise (hors NIU et CNPS)."""
    valeurs = {cle: donnees[cle] for cle in CHAMPS_MODIFIABLES if cle != "email"}
    # Un questionnaire commencé avant le lot 8 n'a pas posé la question de l'email.
    valeurs["email"] = donnees.get("email")
    tva = donnees["assujetti_tva_declare"]
    valeurs["assujetti_tva_declare"] = None if tva == INCONNU else tva == "oui"
    return valeurs


def parcours_actif(session: Session, conversation: Conversation) -> Parcours | None:
    return session.scalars(
        select(Parcours).where(
            Parcours.conversation_id == conversation.id, Parcours.statut.in_((EN_COURS, EN_PAUSE))
        )
    ).first()
