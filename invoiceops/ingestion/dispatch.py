from typing import Protocol

from celery import Celery

from invoiceops.config import get_settings


class JobDispatcher(Protocol):
    def enqueue(self, job_id: str) -> None: ...


class TaskSender(Protocol):
    def send_task(
        self,
        name: str,
        *,
        args: list[str],
        headers: dict[str, str] | None,
    ) -> object: ...


class CeleryJobDispatcher:
    def __init__(self, client: TaskSender | None = None) -> None:
        settings = get_settings()
        self.client = client or Celery(
            "invoiceops-producer",
            broker=settings.redis_url,
            backend=settings.redis_url,
        )

    def enqueue(self, job_id: str) -> None:
        from invoiceops.observability.context import get_request_id

        request_id = get_request_id()
        headers = {"x-request-id": request_id} if request_id is not None else None
        self.client.send_task(
            "invoiceops.process_document",
            args=[job_id],
            headers=headers,
        )

