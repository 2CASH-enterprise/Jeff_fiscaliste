"""Normalisation des textes reçus : une seule règle, utilisée par tous les parcours."""
import re
import unicodedata


def normaliser(texte: str) -> str:
    """Minuscules, sans accents ni ponctuation, espaces réduits."""
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", sans_accents.lower())).strip()
