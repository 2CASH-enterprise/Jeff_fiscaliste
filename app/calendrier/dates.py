"""Dates en français et calcul des échéances : une seule règle de calcul, dans le code.

Formes d'échéance acceptées dans le champ `echeance_calcul` d'une règle :
  {"type": "jour_du_mois_suivant", "jour": 15}               — mensuel : période = mois précédent
  {"type": "jour_du_mois_suivant_le_trimestre", "jour": 15}  — trimestriel : en janvier, avril, juillet, octobre
  {"type": "date_annuelle", "mois": 3, "jour": 15}            — annuel

Aucun report automatique n'est appliqué (décision du lot 5) : la date reste la date.
"""
from dataclasses import dataclass
from datetime import date

MOIS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
JOURS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

MENSUEL = "jour_du_mois_suivant"
TRIMESTRIEL = "jour_du_mois_suivant_le_trimestre"
ANNUEL = "date_annuelle"
PERIODICITE_ATTENDUE = {MENSUEL: "mensuelle", TRIMESTRIEL: "trimestrielle", ANNUEL: "annuelle"}
JOUR_MAX = 28  # toujours valide, quel que soit le mois


class EcheanceInvalide(ValueError):
    pass


@dataclass
class Echeance:
    date_limite: date
    periode: str  # ex. « septembre 2026 », « 3e trimestre 2026 », « année 2027 »


def formater_date(jour: date) -> str:
    """date(2026, 10, 15) → « jeudi 15 octobre 2026 »."""
    premier = "1er" if jour.day == 1 else str(jour.day)
    return f"{JOURS[jour.weekday()]} {premier} {MOIS[jour.month - 1]} {jour.year}"


def formater_delai(date_limite: date, aujourd_hui: date) -> str:
    jours = (date_limite - aujourd_hui).days
    if jours == 0:
        return "aujourd'hui"
    if jours == 1:
        return "demain"
    return f"dans {jours} jours"


def valider(calcul, periodicite: str | None) -> None:
    if not isinstance(calcul, dict) or calcul.get("type") not in PERIODICITE_ATTENDUE:
        raise EcheanceInvalide("type d'échéance inconnu.")
    attendus = {"type", "jour"} | ({"mois"} if calcul["type"] == ANNUEL else set())
    if set(calcul) != attendus:
        raise EcheanceInvalide(f"champs attendus : {', '.join(sorted(attendus))}.")
    if PERIODICITE_ATTENDUE[calcul["type"]] != periodicite:
        raise EcheanceInvalide(f"« {calcul['type']} » ne correspond pas à la périodicité {periodicite!r}.")
    for cle, maximum in (("jour", JOUR_MAX), ("mois", 12)):
        if cle in calcul:
            valeur = calcul[cle]
            if not isinstance(valeur, int) or isinstance(valeur, bool) or not 1 <= valeur <= maximum:
                raise EcheanceInvalide(f"« {cle} » doit être un entier entre 1 et {maximum}.")


def mois_suivant(annee: int, mois: int) -> tuple[int, int]:
    return (annee + 1, 1) if mois == 12 else (annee, mois + 1)


def mois_precedent(annee: int, mois: int) -> tuple[int, int]:
    return (annee - 1, 12) if mois == 1 else (annee, mois - 1)


def prochaine_echeance(calcul: dict, aujourd_hui: date) -> Echeance:
    """Première échéance qui tombe aujourd'hui ou plus tard."""
    jour = calcul["jour"]
    if calcul["type"] == MENSUEL:
        annee, mois = aujourd_hui.year, aujourd_hui.month
        if aujourd_hui.day > jour:
            annee, mois = mois_suivant(annee, mois)
        annee_periode, mois_periode = mois_precedent(annee, mois)
        return Echeance(date(annee, mois, jour), f"{MOIS[mois_periode - 1]} {annee_periode}")

    if calcul["type"] == TRIMESTRIEL:
        annee, mois = aujourd_hui.year, aujourd_hui.month
        while True:
            if mois in (1, 4, 7, 10) and date(annee, mois, jour) >= aujourd_hui:
                trimestre = (mois - 1) // 3 or 4
                annee_periode = annee - 1 if mois == 1 else annee
                ordinal = "1er" if trimestre == 1 else f"{trimestre}e"
                return Echeance(date(annee, mois, jour), f"{ordinal} trimestre {annee_periode}")
            annee, mois = mois_suivant(annee, mois)

    candidate = date(aujourd_hui.year, calcul["mois"], jour)
    if candidate < aujourd_hui:
        candidate = date(aujourd_hui.year + 1, calcul["mois"], jour)
    return Echeance(candidate, f"année {candidate.year}")
