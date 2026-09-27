import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from invoiceops.db import SessionLocal
from invoiceops.extraction.failures import (
    TERMINAL_EXTRACTION_ERRORS,
    extraction_error_code,
    safe_extraction_error_message,
)
from invoiceops.jobs.events import append_job_event
from invoiceops.models import Document, ExtractionRun, IngestionJob, JobStatus
from invoiceops.observability.context import request_id_or_new, reset_request_id, set_request_id
from invoiceops.observability.metrics import metrics
from invoiceops.observability.tracing import span
from invoiceops.schemas.jobs import JobEventType
from workers.extraction.celery_app import celery_app
from workers.extraction.factory import build_extraction_service

logger = logging.getLogger(__name__)
MAX_RETRIES = 3
DocumentProcessor = Callable[[Document], object]


def _safe_extraction_summary(processed: object) -> dict[str, object]:
    if not isinstance(processed, ExtractionRun):
        return {}
    output = processed.output_json if isinstance(processed.output_json, dict) else {}
    header_names = ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")
    field_count = 0
    for name in header_names:
        field = output.get(name)
        if isinstance(field, dict) and field.get("value") is not None:
            field_count += 1
    raw_lines = output.get("line_items", [])
    line_item_count = len(raw_lines) if isinstance(raw_lines, list) else 0
    return {
        "field_count": field_count,
        "line_item_count": line_item_count,
        "fallback_used": processed.extractor_name == "hybrid-routed",
        "used_ocr": bool(processed.used_ocr),
    }


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

    created_at = job.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    metrics.observe(
        "queue_duration", max(0.0, (datetime.now(UTC) - created_at).total_seconds()), "jobs"
    )
    job.status = JobStatus.PROCESSING
    job.error_code = None
    job.error_message = None
    append_job_event(
        session,
        job_id=job.id,
        event_key="extraction.started",
        event_type=JobEventType.EXTRACTION_STARTED,
        stage="extraction",
        status="started",
        message="Invoice extraction started",
    )
    session.commit()
    metrics.add("jobs", "jobs", status=JobStatus.PROCESSING.value)
    logger.info(
        "Document processing started",
        extra={
            "event": "worker.processing",
            "job_id": str(job.id),
            "document_id": str(job.document_id),
            "status": job.status.value,
        },
    )

    processed = processor(job.document)

    job.status = JobStatus.SUCCEEDED
    append_job_event(
        session,
        job_id=job.id,
        event_key="extraction.completed",
        event_type=JobEventType.EXTRACTION_COMPLETED,
        stage="extraction",
        status="completed",
        message="Invoice extraction completed",
        payload=_safe_extraction_summary(processed),
    )
    append_job_event(
        session,
        job_id=job.id,
        event_key="processing.completed",
        event_type=JobEventType.PROCESSING_COMPLETED,
        stage="processing",
        status="completed",
        message="Invoice processing completed",
    )
    session.commit()
    metrics.add("jobs", "jobs", status=JobStatus.SUCCEEDED.value)
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
    if terminal:
        append_job_event(
            session,
            job_id=job.id,
            event_key="processing.failed",
            event_type=JobEventType.PROCESSING_FAILED,
            stage="processing",
            status="failed",
            message="Invoice processing failed",
            payload={"error_code": job.error_code},
        )
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
    headers = getattr(self.request, "headers", None) or {}
    token = set_request_id(request_id_or_new(headers.get("x-request-id")))
    try:
        _process_document(self, job_id)
    finally:
        reset_request_id(token)


def _process_document(self: Any, job_id: str) -> None:
    parsed_job_id = uuid.UUID(job_id)
    try:
        with span("worker.extract", {"messaging.operation": "process"}):
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
        metrics.add("jobs", "jobs", status=JobStatus.FAILED.value)
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
        metrics.add(
            "jobs",
            "jobs",
            status=JobStatus.FAILED.value if terminal else JobStatus.QUEUED.value,
        )
        if terminal:
            raise
        raise self.retry(exc=exc, countdown=min(2**retry_count, 30)) from exc
