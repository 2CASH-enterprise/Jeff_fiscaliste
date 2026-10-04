"""Chargement du fichier de règles d'un pays dans la base : tout ou rien.

Le fichier (relu par le fiscaliste, versionné dans Git) est entièrement vérifié avant la
moindre écriture. Une règle déjà chargée ne change jamais de contenu : toute modification
passe par une nouvelle version. Seul le statut (à valider → publiée → retirée) peut évoluer
sur une version existante.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendrier.dates import EcheanceInvalide
from app.calendrier.dates import valider as valider_echeance
from app.referentiel.models import Juridiction
from app.regles.conditions import ConditionInvalide, valider
from app.regles.models import PERIODICITES, STATUTS, TYPES, Regle

REQUIS = {"code", "version", "type", "impot", "titre", "description", "condition", "applicable_du", "statut"}
OPTIONNELS = {
    "periodicite", "echeance", "echeance_calcul", "source_texte", "source_article", "source_url",
    "applicable_au", "ordre",
}
CONTENU = (REQUIS | OPTIONNELS) - {"statut"}


class ReglesInvalides(ValueError):
    def __init__(self, erreurs: list[str]):
        super().__init__("\n".join(erreurs))
        self.erreurs = erreurs


@dataclass
class Bilan:
    ajoutees: list[str] = field(default_factory=list)
    inchangees: list[str] = field(default_factory=list)
    statut_modifie: list[str] = field(default_factory=list)


def lire_date(valeur, nom: str, erreurs: list[str]) -> date | None:
    try:
        return date.fromisoformat(valeur)
    except (TypeError, ValueError):
        erreurs.append(f"{nom} : date invalide {valeur!r} (format AAAA-MM-JJ).")
        return None


def verifier_regle(brute: dict, position: int) -> tuple[dict, list[str]]:
    """Renvoie la règle prête à enregistrer et la liste de ses erreurs."""
    nom = f"règle n° {position} ({brute.get('code', 'sans code')})" if isinstance(brute, dict) else f"règle n° {position}"
    if not isinstance(brute, dict):
        return {}, [f"{nom} : doit être un objet."]
    erreurs = []
    manquants = REQUIS - set(brute)
    if manquants:
        erreurs.append(f"{nom} : champs manquants : {', '.join(sorted(manquants))}.")
    inconnus = set(brute) - REQUIS - OPTIONNELS
    if inconnus:
        erreurs.append(f"{nom} : champs inconnus : {', '.join(sorted(inconnus))}.")
    if erreurs:
        return {}, erreurs

    if not isinstance(brute["code"], str) or not re.fullmatch(r"[A-Z0-9_]{3,60}", brute["code"]):
        erreurs.append(f"{nom} : code invalide (majuscules, chiffres et _ uniquement).")
    if not isinstance(brute["version"], int) or isinstance(brute["version"], bool) or brute["version"] < 1:
        erreurs.append(f"{nom} : la version doit être un entier supérieur ou égal à 1.")
    if brute["type"] not in TYPES:
        erreurs.append(f"{nom} : type inconnu {brute['type']!r}.")
    if brute["statut"] not in STATUTS:
        erreurs.append(f"{nom} : statut inconnu {brute['statut']!r}.")
    periodicite = brute.get("periodicite")
    if periodicite is not None and periodicite not in PERIODICITES:
        erreurs.append(f"{nom} : périodicité inconnue {periodicite!r}.")
    if brute["type"] == "obligation" and periodicite is None:
        erreurs.append(f"{nom} : une obligation doit avoir une périodicité.")
    for texte in ("impot", "titre", "description"):
        if not isinstance(brute[texte], str) or not brute[texte].strip():
            erreurs.append(f"{nom} : « {texte} » ne peut pas être vide.")
    try:
        valider(brute["condition"])
    except ConditionInvalide as erreur:
        erreurs.append(f"{nom} : condition invalide : {erreur}")
    if brute.get("echeance_calcul") is not None:
        try:
            valider_echeance(brute["echeance_calcul"], periodicite)
        except EcheanceInvalide as erreur:
            erreurs.append(f"{nom} : échéance calculable invalide : {erreur}")

    du = lire_date(brute["applicable_du"], f"{nom} applicable_du", erreurs)
    au = None
    if brute.get("applicable_au") is not None:
        au = lire_date(brute["applicable_au"], f"{nom} applicable_au", erreurs)
    if du and au and au < du:
        erreurs.append(f"{nom} : applicable_au est antérieure à applicable_du.")

    regle = {
        **{cle: brute.get(cle) for cle in OPTIONNELS},
        **{cle: brute[cle] for cle in REQUIS},
        "applicable_du": du,
        "applicable_au": au,
        "ordre": brute.get("ordre", 100),
    }
    return regle, erreurs


def contenu(regle) -> dict:
    """Ce qui ne doit jamais changer sur une version déjà chargée."""
    if isinstance(regle, Regle):
        return {cle: getattr(regle, cle) for cle in CONTENU}
    return {cle: regle[cle] for cle in CONTENU}


def charger(session: Session, donnees: dict) -> Bilan:
    erreurs: list[str] = []
    if not isinstance(donnees, dict) or "juridiction" not in donnees or not isinstance(donnees.get("regles"), list):
        raise ReglesInvalides(["Le fichier doit contenir « juridiction » et une liste « regles »."])
    juridiction = donnees["juridiction"]
    if session.get(Juridiction, juridiction) is None:
        raise ReglesInvalides([f"Juridiction inconnue : {juridiction!r}."])

    regles, vues = [], set()
    for position, brute in enumerate(donnees["regles"], start=1):
        regle, erreurs_regle = verifier_regle(brute, position)
        erreurs.extend(erreurs_regle)
        if not erreurs_regle:
            cle = (regle["code"], regle["version"])
            if cle in vues:
                erreurs.append(f"{regle['code']} version {regle['version']} : présente deux fois dans le fichier.")
            vues.add(cle)
            regles.append(regle)

    existantes = {
        (r.code, r.version): r
        for r in session.scalars(select(Regle).where(Regle.juridiction_code == juridiction))
    }
    for regle in regles:
        deja = existantes.get((regle["code"], regle["version"]))
        if deja is not None and contenu(deja) != contenu(regle):
            erreurs.append(
                f"{regle['code']} version {regle['version']} : déjà chargée avec un autre contenu. "
                "Créez une nouvelle version au lieu de modifier celle-ci."
            )
    if erreurs:
        raise ReglesInvalides(erreurs)

    bilan = Bilan()
    for regle in regles:
        nom = f"{regle['code']} v{regle['version']}"
        deja = existantes.get((regle["code"], regle["version"]))
        if deja is None:
            session.add(Regle(juridiction_code=juridiction, **regle))
            bilan.ajoutees.append(nom)
        elif deja.statut != regle["statut"]:
            deja.statut = regle["statut"]
            bilan.statut_modifie.append(nom)
        else:
            bilan.inchangees.append(nom)
    session.flush()
    return bilan


def charger_fichier(session: Session, chemin: Path) -> Bilan:
    try:
        donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        raise ReglesInvalides([f"Fichier JSON illisible : {erreur}"])
    return charger(session, donnees)
