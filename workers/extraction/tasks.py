import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from invoiceops.db import SessionLocal
from invoiceops.models import Document, IngestionJob, JobStatus
from workers.extraction.celery_app import celery_app

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
DocumentProcessor = Callable[[Document], None]


def placeholder_pipeline(_document: Document) -> None:
    """The next vertical slice replaces this with preprocessing and OCR."""


def run_job(
    session: Session,
    job_id: uuid.UUID,
    processor: DocumentProcessor = placeholder_pipeline,
) -> bool:
    """Run an idempotent state transition; return false when work was already complete."""
    job = session.get(IngestionJob, job_id)
    if job is None:
        logger.warning(
            "Worker received an unknown job",
            extra={"event": "worker.job_missing", "job_id": str(job_id)},
        )
        return False
    if job.status == JobStatus.SUCCEEDED:
        logger.info(
            "Redelivered completed job required no work",
            extra={
                "event": "worker.already_succeeded",
                "job_id": str(job.id),
                "document_id": str(job.document_id),
                "status": job.status.value,
            },
        )
        return False

    job.status = JobStatus.PROCESSING
    job.error_code = None
    job.error_message = None
    session.commit()
    logger.info(
        "Document processing started",
        extra={
            "event": "worker.processing",
            "job_id": str(job.id),
            "document_id": str(job.document_id),
            "status": job.status.value,
        },
    )

    processor(job.document)

    job.status = JobStatus.SUCCEEDED
    session.commit()
    logger.info(
        "Document processing succeeded",
        extra={
            "event": "worker.succeeded",
            "job_id": str(job.id),
            "document_id": str(job.document_id),
            "status": job.status.value,
        },
    )
    return True


def record_failure(session: Session, job_id: uuid.UUID, terminal: bool) -> None:
    job = session.get(IngestionJob, job_id)
    if job is None or job.status == JobStatus.SUCCEEDED:
        return
    job.status = JobStatus.FAILED if terminal else JobStatus.QUEUED
    job.error_code = "processing_failed" if terminal else None
    job.error_message = "Document processing failed" if terminal else None
    session.commit()


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="invoiceops.process_document",
    max_retries=MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_document(self: Any, job_id: str) -> None:
    """Retry transient failures safely and make terminal failure visible via job status."""
    parsed_job_id = uuid.UUID(job_id)
    try:
        with SessionLocal() as session:
            run_job(session, parsed_job_id)
    except Exception as exc:
        retry_count = int(self.request.retries)
        terminal = retry_count >= MAX_RETRIES
        with SessionLocal() as session:
            record_failure(session, parsed_job_id, terminal=terminal)
        logger.exception(
            "Document processing failed",
            extra={
                "event": "worker.failed" if terminal else "worker.retry_scheduled",
                "job_id": job_id,
                "status": JobStatus.FAILED.value if terminal else JobStatus.QUEUED.value,
                "retry_count": retry_count,
                "error_code": "processing_failed" if terminal else "retry_scheduled",
            },
        )
        if terminal:
            raise
        raise self.retry(exc=exc, countdown=min(2**retry_count, 30)) from exc
