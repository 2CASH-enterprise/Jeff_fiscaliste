"""Date du jour dans le fuseau horaire d'une juridiction (jamais celui du serveur)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo


def aujourd_hui(fuseau_horaire: str) -> date:
    return datetime.now(ZoneInfo(fuseau_horaire)).date()
