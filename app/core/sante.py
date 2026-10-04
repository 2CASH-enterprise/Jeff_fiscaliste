"""Vérification de l'état de l'application : base de données et Redis.

Une vérification qui échoue n'est jamais présentée comme réussie : la page /sante répond 503
dès qu'un composant ne répond pas.
"""
import redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine

OK = "ok"
INDISPONIBLE = "indisponible"


def verifier_base() -> str:
    try:
        with get_engine().connect() as connexion:
            connexion.execute(text("SELECT 1"))
        return OK
    except Exception:
        return INDISPONIBLE


def verifier_redis() -> str:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        client.ping()
        return OK
    except Exception:
        return INDISPONIBLE


def etat_general() -> dict:
    composants = {"base": verifier_base(), "redis": verifier_redis()}
    tout_va_bien = all(valeur == OK for valeur in composants.values())
    return {"statut": OK if tout_va_bien else INDISPONIBLE, **composants}
