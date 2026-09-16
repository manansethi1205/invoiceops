from typing import Protocol


class JobDispatcher(Protocol):
    def enqueue(self, job_id: str) -> None: ...


class CeleryJobDispatcher:
    def enqueue(self, job_id: str) -> None:
        from workers.extraction.tasks import process_document

        process_document.delay(job_id)

