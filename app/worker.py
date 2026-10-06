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
    # Lot 8 : la boîte d'envoi est vidée chaque minute (codes de confirmation, rappels).
    "envoyer-emails": {"task": "jeff.envoyer_emails", "schedule": crontab()},
    # Lot 9 : reprise des réponses WhatsApp restées en attente.
    "envoyer-whatsapp": {"task": "jeff.envoyer_whatsapp", "schedule": crontab()},
    # Lot 17 : chaque nuit à 4 h, les demandes de code de plus de 7 jours sont effacées.
    "nettoyer-espace": {"task": "jeff.nettoyer_espace", "schedule": crontab(hour=4, minute=0)},
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


@celery_app.task(name="jeff.envoyer_emails")
def tache_envoyer_emails() -> dict:
    from app import models as _modeles  # noqa: F401 (toutes les tables connues)
    from app.core.db import get_session
    from app.emails.envoi import envoyer_en_attente

    session = get_session()
    try:
        bilan = envoyer_en_attente(session)
        return {"envoyes": bilan.envoyes, "echecs": bilan.echecs, "desactive": bilan.desactive}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="jeff.envoyer_whatsapp")
def tache_envoyer_whatsapp() -> dict:
    from app import models as _modeles  # noqa: F401 (toutes les tables connues)
    from app.core.db import get_session
    from app.whatsapp.envoi import envoyer_en_attente

    session = get_session()
    try:
        bilan = envoyer_en_attente(session)
        return {"envoyes": bilan.envoyes, "echecs": bilan.echecs, "desactive": bilan.desactive}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(name="jeff.nettoyer_espace")
def tache_nettoyer_espace() -> int:
    from app import models as _modeles  # noqa: F401 (toutes les tables connues)
    from app.core.db import get_session
    from app.espace.connexion import nettoyer

    session = get_session()
    try:
        effacees = nettoyer(session)
        session.commit()
        return effacees
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
