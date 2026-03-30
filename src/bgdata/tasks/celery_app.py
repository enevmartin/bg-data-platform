"""Celery application factory."""
from celery import Celery

from bgdata.config import get_settings

cfg = get_settings()

celery_app = Celery(
    "bg_data_platform",
    broker=cfg.celery_broker_url,
    backend=cfg.celery_result_backend,
    include=[
        "bgdata.tasks.scrape",
        "bgdata.tasks.process",
        "bgdata.tasks.analyze",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Europe/Sofia",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=86400,  # 24 hours
)
