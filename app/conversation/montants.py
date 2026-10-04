"""Lecture des montants et des nombres écrits par les clients : une seule règle, dans le code.

Un montant n'est jamais interprété par l'IA. Formats compris (en FCFA, sans centimes) :
« 150000000 », « 150 000 000 », « 150.000.000 », « 150,000,000 », « 150 millions »,
« 150M », « 1,5 milliard », « 500 mille », « 500k », avec ou sans « FCFA ».
"""
import re
from decimal import Decimal, InvalidOperation

from app.conversation.normalisation import normaliser

MONTANT_MAX = 10**13  # 10 000 milliards de FCFA

MULTIPLICATEURS = {
    "milliard": 10**9, "milliards": 10**9, "md": 10**9, "mds": 10**9, "mrd": 10**9,
    "million": 10**6, "millions": 10**6, "m": 10**6, "mio": 10**6, "mln": 10**6,
    "mille": 10**3, "k": 10**3,
}

UNITES_MONETAIRES = r"\b(f\s*cfa|fcfa|xaf|francs?\s+cfa|francs?|cfa|f)\b"
ESPACES = r"[\s  ]"


class LectureImpossible(ValueError):
    pass


def lire_montant(texte: str) -> int:
    """Renvoie un montant entier en FCFA, ou lève LectureImpossible."""
    if texte is None:
        raise LectureImpossible
    brut = texte.lower().strip()
    brut = re.sub(UNITES_MONETAIRES, " ", brut)
    brut = re.sub(r"\bde\b", " ", brut).strip()
    correspondance = re.fullmatch(rf"([\d.,\s  ]+?){ESPACES}*([a-z]+)?", brut)
    if not correspondance:
        raise LectureImpossible
    chiffres = re.sub(ESPACES, "", correspondance.group(1))
    unite = correspondance.group(2)
    if not chiffres or not re.search(r"\d", chiffres):
        raise LectureImpossible

    if unite is not None:
        if unite not in MULTIPLICATEURS:
            raise LectureImpossible
        if not re.fullmatch(r"\d+([.,]\d+)?", chiffres):
            raise LectureImpossible
        try:
            valeur = Decimal(chiffres.replace(",", ".")) * MULTIPLICATEURS[unite]
        except InvalidOperation:
            raise LectureImpossible
        if valeur != valeur.to_integral_value():
            raise LectureImpossible
        montant = int(valeur)
    elif re.fullmatch(r"\d+", chiffres):
        montant = int(chiffres)
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", chiffres) or re.fullmatch(r"\d{1,3}(,\d{3})+", chiffres):
        montant = int(re.sub(r"[.,]", "", chiffres))
    else:
        raise LectureImpossible

    if montant > MONTANT_MAX:
        raise LectureImpossible
    return montant


MOTS_ZERO = {
    "0", "aucun", "aucune", "zero", "personne", "non",
    "aucun salarie", "aucun salaries", "pas de salarie", "pas de salaries",
}


def lire_nombre_entier(texte: str, maximum: int) -> int:
    """Nombre entier positif (ex. nombre de salariés), « aucun » compris comme 0."""
    if texte is None:
        raise LectureImpossible
    if normaliser(texte) in MOTS_ZERO:
        return 0
    # Les chiffres sont lus sur le texte brut : « 3,5 » ou « -1 » ne doivent pas devenir 35 ou 1.
    chiffres = re.sub(ESPACES, "", texte)
    if not re.fullmatch(r"\d+", chiffres):
        raise LectureImpossible
    nombre = int(chiffres)
    if nombre > maximum:
        raise LectureImpossible
    return nombre


ESPACE_INSECABLE = "\u00a0"


def formater_montant(montant: int) -> str:
    """150000000 → « 150 000 000 FCFA », avec des espaces insécables (jamais coupé en fin de ligne)."""
    return f"{montant:,}".replace(",", ESPACE_INSECABLE) + ESPACE_INSECABLE + "FCFA"
