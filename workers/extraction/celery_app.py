from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from invoiceops.config import get_settings
from invoiceops.db import engine
from invoiceops.logging import configure_logging
from invoiceops.observability.setup import setup_observability, shutdown_observability

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


def _initialize_worker_telemetry(**kwargs: object) -> None:
    del kwargs
    setup_observability(settings, service_name="invoiceops-worker", engine=engine)


def _shutdown_worker_telemetry(**kwargs: object) -> None:
    del kwargs
    shutdown_observability()


worker_process_init.connect(_initialize_worker_telemetry, weak=False)
worker_process_shutdown.connect(_shutdown_worker_telemetry, weak=False)
