"""Évaluation des conditions de règles sur le profil d'une entreprise : oui, non ou incertain.

Une condition est un petit arbre JSON, écrit dans le fichier de règles :
  {"toujours": true}
  {"champ": "nombre_salaries", "op": "superieur", "valeur": 0}
  {"tous": [cond, cond]}      — toutes vraies
  {"un_parmi": [cond, cond]}  — au moins une vraie
  {"non": cond}

Une réponse « je ne sais pas » (valeur absente) rend la comparaison INCERTAINE, et
l'incertitude se propage selon la logique à trois valeurs : un « non » certain l'emporte
dans « tous », un « oui » certain l'emporte dans « un_parmi ».
"""
from typing import Any

OUI = "oui"
NON = "non"
INCERTAIN = "incertain"

CHAMPS = {
    "forme_juridique",
    "secteur",
    "chiffre_affaires_annuel",
    "regime_declare",
    "assujetti_tva_declare",
    "nombre_salaries",
    "numero_employeur_cnps",
}

COMPARAISONS = {
    "egal": lambda a, b: a == b,
    "different": lambda a, b: a != b,
    "superieur": lambda a, b: a > b,
    "superieur_ou_egal": lambda a, b: a >= b,
    "inferieur": lambda a, b: a < b,
    "inferieur_ou_egal": lambda a, b: a <= b,
    "dans": lambda a, b: a in b,
}
# Opérateurs qui portent sur la présence de la valeur : ils ne sont jamais incertains.
PRESENCE = {"est_vide", "est_renseigne"}


class ConditionInvalide(ValueError):
    pass


def valider(condition: Any) -> None:
    """Vérifie la forme d'une condition avant tout chargement ; lève ConditionInvalide."""
    if not isinstance(condition, dict) or len(condition) == 0:
        raise ConditionInvalide("Une condition doit être un objet non vide.")
    if "toujours" in condition:
        if condition != {"toujours": True}:
            raise ConditionInvalide("« toujours » s'écrit {\"toujours\": true}.")
        return
    if "tous" in condition or "un_parmi" in condition:
        cle = "tous" if "tous" in condition else "un_parmi"
        sous = condition[cle]
        if len(condition) != 1 or not isinstance(sous, list) or not sous:
            raise ConditionInvalide(f"« {cle} » attend une liste non vide de conditions.")
        for element in sous:
            valider(element)
        return
    if "non" in condition:
        if len(condition) != 1:
            raise ConditionInvalide("« non » attend une seule condition.")
        valider(condition["non"])
        return
    champ, op = condition.get("champ"), condition.get("op")
    if champ not in CHAMPS:
        raise ConditionInvalide(f"Champ inconnu : {champ!r}.")
    if op in PRESENCE:
        if set(condition) != {"champ", "op"}:
            raise ConditionInvalide(f"« {op} » ne prend pas de valeur.")
        return
    if op not in COMPARAISONS:
        raise ConditionInvalide(f"Opérateur inconnu : {op!r}.")
    if set(condition) != {"champ", "op", "valeur"}:
        raise ConditionInvalide("Une comparaison attend exactement champ, op et valeur.")
    if op == "dans" and not isinstance(condition["valeur"], list):
        raise ConditionInvalide("« dans » attend une liste de valeurs.")


def evaluer(condition: dict, profil: dict) -> str:
    if "toujours" in condition:
        return OUI
    if "tous" in condition:
        resultats = [evaluer(c, profil) for c in condition["tous"]]
        if NON in resultats:
            return NON
        return INCERTAIN if INCERTAIN in resultats else OUI
    if "un_parmi" in condition:
        resultats = [evaluer(c, profil) for c in condition["un_parmi"]]
        if OUI in resultats:
            return OUI
        return INCERTAIN if INCERTAIN in resultats else NON
    if "non" in condition:
        resultat = evaluer(condition["non"], profil)
        return {OUI: NON, NON: OUI}.get(resultat, INCERTAIN)

    valeur = profil.get(condition["champ"])
    op = condition["op"]
    if op == "est_vide":
        return OUI if valeur is None else NON
    if op == "est_renseigne":
        return NON if valeur is None else OUI
    if valeur is None:
        return INCERTAIN
    try:
        return OUI if COMPARAISONS[op](valeur, condition["valeur"]) else NON
    except TypeError:
        raise ConditionInvalide(f"Comparaison impossible sur {condition['champ']!r} : types différents.")
