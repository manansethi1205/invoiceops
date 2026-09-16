from celery import Celery

from invoiceops.config import get_settings
from invoiceops.logging import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
celery_app = Celery(
    "invoiceops",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.extraction.tasks"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
)
