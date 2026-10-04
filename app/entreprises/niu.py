"""Numéro d'identifiant unique (NIU) : une seule règle de normalisation, utilisée partout.

Le NIU sert de clé d'entreprise au sein d'une juridiction, et plus tard de point de
rapprochement avec les comptes Naomy et Bob. Le contrôle de format propre à chaque pays
sera ajouté avec les règles de la juridiction, après validation par le fiscaliste.
"""
import re

LONGUEUR_MAX = 20


class NiuInvalide(ValueError):
    pass


def normaliser_niu(valeur: str) -> str:
    """Retire espaces et tirets, passe en majuscules, refuse une valeur vide ou trop longue."""
    if valeur is None:
        raise NiuInvalide("Le NIU est obligatoire.")
    niu = re.sub(r"[\s\-]", "", valeur).upper()
    if not niu:
        raise NiuInvalide("Le NIU est obligatoire.")
    if len(niu) > LONGUEUR_MAX:
        raise NiuInvalide("Le NIU est trop long.")
    if not niu.isalnum():
        raise NiuInvalide("Le NIU ne doit contenir que des lettres et des chiffres.")
    return niu
