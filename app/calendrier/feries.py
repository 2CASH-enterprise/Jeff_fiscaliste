"""Jours fériés du Cameroun : sert uniquement à avertir le client, jamais à déplacer une date.

- Dates fixes et fêtes liées à Pâques : calculées.
- Fêtes musulmanes (Djouldé Soumaé, Djouldé Kaïrou) : fixées chaque année par les autorités,
  saisies dans donnees/feries_mobiles_cm.json (dates estimées tant qu'elles ne sont pas confirmées).
Liste à valider avec le fiscaliste.
"""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

FICHIER_MOBILES = Path(__file__).resolve().parent / "donnees" / "feries_mobiles_cm.json"

FIXES = {
    (1, 1): "Jour de l'An",
    (2, 11): "Fête de la Jeunesse",
    (5, 1): "Fête du Travail",
    (5, 20): "Fête nationale",
    (8, 15): "Assomption",
    (12, 25): "Noël",
}


def paques(annee: int) -> date:
    """Dimanche de Pâques (calendrier grégorien, algorithme de Meeus/Jones/Butcher)."""
    a, b, c = annee % 19, annee // 100, annee % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mois = (h + l - 7 * m + 114) // 31
    jour = (h + l - 7 * m + 114) % 31 + 1
    return date(annee, mois, jour)


@lru_cache
def feries_mobiles() -> dict[date, str]:
    donnees = json.loads(FICHIER_MOBILES.read_text(encoding="utf-8"))
    return {date.fromisoformat(f["date"]): f["nom"] for f in donnees["feries"]}


def jour_ferie(jour: date) -> str | None:
    """Nom du jour férié, ou None."""
    if (jour.month, jour.day) in FIXES:
        return FIXES[(jour.month, jour.day)]
    dimanche_paques = paques(jour.year)
    if jour == dimanche_paques - timedelta(days=2):
        return "Vendredi saint"
    if jour == dimanche_paques + timedelta(days=39):
        return "Ascension"
    return feries_mobiles().get(jour)
