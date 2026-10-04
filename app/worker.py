"""Application Celery : tâches de fond (rappels, OCR par lots, veille DGI…), ajoutées lot après lot."""
from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

celery_app = Celery("jeff", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.timezone = "Africa/Douala"
celery_app.conf.task_acks_late = True
celery_app.conf.beat_schedule = {
    # Lot 7 : chaque matin à 7 h 30, heure de Douala.
    "preparer-rappels": {"task": "jeff.preparer_rappels", "schedule": crontab(hour=7, minute=30)},
}


@celery_app.task(name="jeff.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="jeff.preparer_rappels")
def tache_preparer_rappels() -> int:
    from app import models as _modeles  # noqa: F401 (toutes les tables connues)
    from app.core.db import get_session
    from app.rappels.preparation import preparer_rappels

    session = get_session()
    try:
        nombre = preparer_rappels(session)
        session.commit()
        return nombre
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
