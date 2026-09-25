import time
import uuid
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceops.extraction.errors import DocumentExtractionError, OcrUnavailableError
from invoiceops.extraction.failures import (
    extraction_error_code,
    safe_extraction_error_message,
)
from invoiceops.extraction.pipeline import InvoiceExtractor
from invoiceops.extraction.version import SCHEMA_VERSION
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.models import Document, ExtractionRun, ExtractionRunStatus
from invoiceops.observability.metrics import metrics
from invoiceops.observability.tracing import span
from invoiceops.schemas.extraction import DocumentText, Invoice


class TextExtractor(Protocol):
    def extract(self, body: bytes, content_type: str) -> DocumentText: ...


class ExtractionService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        text_extractor: TextExtractor,
        invoice_extractor: InvoiceExtractor,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.text_extractor = text_extractor
        self.invoice_extractor = invoice_extractor

    def process(self, document: Document) -> ExtractionRun:
        run = self._get_or_create_run(document.id)
        if run.status == ExtractionRunStatus.SUCCEEDED:
            return run
        run = self._mark_processing(run)
        if run.status == ExtractionRunStatus.SUCCEEDED:
            return run

        started = time.perf_counter()
        try:
            with span("extraction.object_store_download"):
                body = self.object_store.get(document.object_key)
            with span("extraction.preprocessing"):
                document_text = self.text_extractor.extract(body, document.content_type)
            with span(
                "extraction.deterministic",
                {"invoiceops.strategy": self.invoice_extractor.name},
            ):
                extracted = self.invoice_extractor.extract(document_text)
            invoice = Invoice.model_validate(extracted)
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
        except (DocumentExtractionError, ValidationError) as exc:
            self._mark_terminal_failure(run.id, exc)
            metrics.add(
                "extraction",
                "extraction",
                strategy=self.invoice_extractor.name,
                status="FAILED",
            )
            metrics.observe(
                "extraction_duration",
                time.perf_counter() - started,
                "extraction",
                strategy=self.invoice_extractor.name,
                status="FAILED",
            )
            if isinstance(exc, OcrUnavailableError):
                metrics.add("ocr", "ocr", outcome="FAILED")
            raise

        with span("extraction.persistence"):
            self.session.execute(
                update(ExtractionRun)
                .where(ExtractionRun.id == run.id)
                .values(
                    status=ExtractionRunStatus.SUCCEEDED,
                    output_json=invoice.model_dump(mode="json"),
                    used_ocr=document_text.used_ocr,
                    latency_ms=latency_ms,
                    error_code=None,
                    error_message=None,
                    completed_at=datetime.now(UTC),
                )
            )
            self.session.commit()
        metrics.add(
            "extraction",
            "extraction",
            strategy=self.invoice_extractor.name,
            status="SUCCEEDED",
        )
        metrics.observe(
            "extraction_duration",
            latency_ms / 1000,
            "extraction",
            strategy=self.invoice_extractor.name,
            status="SUCCEEDED",
        )
        metrics.add("ocr", "ocr", outcome="USED" if document_text.used_ocr else "NOT_USED")
        return self._require_run(run.id)

    def _find_run(self, document_id: uuid.UUID) -> ExtractionRun | None:
        return self.session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.document_id == document_id,
                ExtractionRun.extractor_name == self.invoice_extractor.name,
                ExtractionRun.extractor_version == self.invoice_extractor.version,
            )
        )

    def _get_or_create_run(self, document_id: uuid.UUID) -> ExtractionRun:
        existing = self._find_run(document_id)
        if existing is not None:
            return existing
        run = ExtractionRun(
            document_id=document_id,
            extractor_name=self.invoice_extractor.name,
            extractor_version=self.invoice_extractor.version,
            schema_version=SCHEMA_VERSION,
            status=ExtractionRunStatus.PROCESSING,
        )
        self.session.add(run)
        try:
            self.session.commit()
            return run
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_run(document_id)
            if concurrent is None:
                raise
            return concurrent

    def _mark_processing(self, run: ExtractionRun) -> ExtractionRun:
        if run.status == ExtractionRunStatus.PROCESSING:
            return run
        self.session.execute(
            update(ExtractionRun)
            .where(
                ExtractionRun.id == run.id,
                ExtractionRun.status != ExtractionRunStatus.SUCCEEDED,
            )
            .values(
                status=ExtractionRunStatus.PROCESSING,
                output_json=None,
                used_ocr=None,
                latency_ms=None,
                error_code=None,
                error_message=None,
                completed_at=None,
            )
        )
        self.session.commit()
        self.session.refresh(run)
        return run

    def _mark_terminal_failure(
        self,
        run_id: uuid.UUID,
        exc: DocumentExtractionError | ValidationError,
    ) -> None:
        self.session.execute(
            update(ExtractionRun)
            .where(
                ExtractionRun.id == run_id,
                ExtractionRun.status != ExtractionRunStatus.SUCCEEDED,
            )
            .values(
                status=ExtractionRunStatus.FAILED,
                output_json=None,
                used_ocr=None,
                latency_ms=None,
                error_code=extraction_error_code(exc),
                error_message=safe_extraction_error_message(exc),
                completed_at=datetime.now(UTC),
            )
        )
        self.session.commit()

    def _require_run(self, run_id: uuid.UUID) -> ExtractionRun:
        run = self.session.get(ExtractionRun, run_id)
        if run is None:
            raise RuntimeError("extraction run disappeared after commit")
        self.session.refresh(run)
        return run
