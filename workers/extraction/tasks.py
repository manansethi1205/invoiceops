import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from invoiceops.db import SessionLocal
from invoiceops.extraction.failures import (
    TERMINAL_EXTRACTION_ERRORS,
    extraction_error_code,
    safe_extraction_error_message,
)
from invoiceops.models import Document, IngestionJob, JobStatus
from workers.extraction.celery_app import celery_app
from workers.extraction.factory import build_extraction_service

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
DocumentProcessor = Callable[[Document], object]


def run_job(
    session: Session,
    job_id: uuid.UUID,
    processor: DocumentProcessor,
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


def record_failure(
    session: Session,
    job_id: uuid.UUID,
    *,
    terminal: bool,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    job = session.get(IngestionJob, job_id)
    if job is None or job.status == JobStatus.SUCCEEDED:
        return
    job.status = JobStatus.FAILED if terminal else JobStatus.QUEUED
    job.error_code = (error_code or "processing_failed") if terminal else None
    job.error_message = (error_message or "Document processing failed") if terminal else None
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
            service = build_extraction_service(session)
            run_job(session, parsed_job_id, service.process)
    except TERMINAL_EXTRACTION_ERRORS as exc:
        error_code = extraction_error_code(exc)
        with SessionLocal() as session:
            record_failure(
                session,
                parsed_job_id,
                terminal=True,
                error_code=error_code,
                error_message=safe_extraction_error_message(exc),
            )
        logger.error(
            "Document processing failed with a terminal extraction error",
            extra={
                "event": "worker.failed",
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "retry_count": int(self.request.retries),
                "error_code": error_code,
                "error_type": type(exc).__name__,
            },
        )
        raise
    except Exception as exc:
        retry_count = int(self.request.retries)
        terminal = retry_count >= MAX_RETRIES
        with SessionLocal() as session:
            record_failure(session, parsed_job_id, terminal=terminal)
        logger.error(
            "Document processing encountered an operational failure",
            extra={
                "event": "worker.failed" if terminal else "worker.retry_scheduled",
                "job_id": job_id,
                "status": JobStatus.FAILED.value if terminal else JobStatus.QUEUED.value,
                "retry_count": retry_count,
                "error_code": "processing_failed" if terminal else "retry_scheduled",
                "error_type": type(exc).__name__,
            },
        )
        if terminal:
            raise
        raise self.retry(exc=exc, countdown=min(2**retry_count, 30)) from exc
