"""Application Celery : tâches de fond (rappels, OCR par lots, veille DGI…), ajoutées lot après lot."""
from celery import Celery

from app.core.config import get_settings

celery_app = Celery("jeff", broker=get_settings().redis_url, backend=get_settings().redis_url)
celery_app.conf.timezone = "Africa/Douala"
celery_app.conf.task_acks_late = True


@celery_app.task(name="jeff.ping")
def ping() -> str:
    return "pong"
