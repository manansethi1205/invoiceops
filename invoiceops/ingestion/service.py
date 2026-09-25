import hashlib
import logging
import uuid
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceops.ingestion.dispatch import JobDispatcher
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.models import Document, IngestionJob
from invoiceops.observability.metrics import metrics
from invoiceops.observability.tracing import span

ALLOWED_CONTENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
FILE_SIGNATURES = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
logger = logging.getLogger(__name__)


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


class DocumentTooLargeError(ValueError):
    pass


@dataclass(frozen=True)
class UploadCommand:
    filename: str
    content_type: str
    body: bytes


@dataclass(frozen=True)
class IngestionResult:
    job: IngestionJob
    created: bool


class IngestionService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        dispatcher: JobDispatcher,
        max_upload_bytes: int,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.dispatcher = dispatcher
        self.max_upload_bytes = max_upload_bytes

    def ingest(self, command: UploadCommand) -> IngestionResult:
        if command.content_type not in ALLOWED_CONTENT_TYPES:
            metrics.add("ingestion", "ingestion", outcome="unsupported_type", deduplicated=False)
            raise UnsupportedDocumentError(command.content_type)
        if not command.body:
            metrics.add("ingestion", "ingestion", outcome="empty", deduplicated=False)
            raise EmptyDocumentError
        if len(command.body) > self.max_upload_bytes:
            metrics.add("ingestion", "ingestion", outcome="too_large", deduplicated=False)
            raise DocumentTooLargeError
        if not command.body.startswith(FILE_SIGNATURES[command.content_type]):
            metrics.add(
                "ingestion", "ingestion", outcome="signature_mismatch", deduplicated=False
            )
            raise UnsupportedDocumentError(
                f"content does not match declared type {command.content_type}"
            )

        document_id = uuid.uuid4()
        safe_name = PurePath(command.filename).name or "upload"
        digest = hashlib.sha256(command.body).hexdigest()
        existing = self._find_existing(digest)
        if existing is not None:
            metrics.add("ingestion", "ingestion", outcome="accepted", deduplicated=True)
            logger.info(
                "Duplicate upload reused existing job",
                extra={
                    "event": "ingestion.deduplicated",
                    "job_id": str(existing.id),
                    "document_id": str(existing.document_id),
                    "sha256": digest,
                    "deduplicated": True,
                },
            )
            return IngestionResult(job=existing, created=False)

        object_key = f"invoices/{document_id}/{safe_name}"
        document = Document(
            id=document_id,
            original_filename=safe_name,
            content_type=command.content_type,
            byte_size=len(command.body),
            sha256=digest,
            object_key=object_key,
        )
        job = IngestionJob(document=document)

        with span("ingestion.object_store_put"):
            self.object_store.put(object_key, command.body, command.content_type)
        try:
            with span("ingestion.transaction"):
                self.session.add(job)
                self.session.commit()
        except IntegrityError:
            self.session.rollback()
            self.object_store.delete(object_key)
            # A concurrent request may have committed the same checksum after our first lookup.
            existing = self._find_existing(digest)
            if existing is None:
                raise
            metrics.add("ingestion", "ingestion", outcome="accepted", deduplicated=True)
            logger.info(
                "Concurrent duplicate upload reused existing job",
                extra={
                    "event": "ingestion.deduplicated",
                    "job_id": str(existing.id),
                    "document_id": str(existing.document_id),
                    "sha256": digest,
                    "deduplicated": True,
                },
            )
            return IngestionResult(job=existing, created=False)
        except Exception:
            self.session.rollback()
            self.object_store.delete(object_key)
            raise

        try:
            with span("ingestion.dispatch"):
                self.dispatcher.enqueue(str(job.id))
        except Exception as exc:
            # The durable queued row lets an operational retry recover dispatch safely.
            self.session.refresh(job)
            logger.error(
                "Job dispatch failed; durable job remains queued",
                extra={
                    "event": "ingestion.dispatch_failed",
                    "job_id": str(job.id),
                    "document_id": str(document.id),
                    "status": job.status.value,
                    "error_code": "dispatch_failed",
                    "error_type": type(exc).__name__,
                },
            )
        logger.info(
            "Invoice accepted and job queued",
            extra={
                "event": "ingestion.accepted",
                "job_id": str(job.id),
                "document_id": str(document.id),
                "sha256": digest,
                "status": job.status.value,
                "deduplicated": False,
                "byte_size": len(command.body),
                "content_type": command.content_type,
            },
        )
        metrics.add("ingestion", "ingestion", outcome="accepted", deduplicated=False)
        metrics.add("jobs", "jobs", status=job.status.value)
        return IngestionResult(job=job, created=True)

    def _find_existing(self, digest: str) -> IngestionJob | None:
        return self.session.scalar(
            select(IngestionJob).join(IngestionJob.document).where(Document.sha256 == digest)
        )
