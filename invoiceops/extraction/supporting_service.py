import time
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceops.cases.events import append_case_event
from invoiceops.extraction.errors import DocumentExtractionError
from invoiceops.extraction.failures import extraction_error_code, safe_extraction_error_message
from invoiceops.extraction.service import TextExtractor
from invoiceops.extraction.supporting import (
    SUPPORTING_EXTRACTOR_NAME,
    SUPPORTING_EXTRACTOR_VERSION,
    SUPPORTING_SCHEMA_VERSION,
    extract_goods_receipt,
    extract_purchase_order,
)
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.models import CaseDocument, PayableCase, SupportingExtractionRun
from invoiceops.observability.metrics import metrics
from invoiceops.schemas.cases import CaseStatus, DocumentRole, SupportingExtractionStatus


class UnsupportedSupportingRoleError(ValueError):
    pass


class SupportingExtractionService:
    def __init__(
        self,
        session: Session,
        object_store: ObjectStore,
        text_extractor: TextExtractor,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.text_extractor = text_extractor

    def process(self, attachment: CaseDocument) -> SupportingExtractionRun:
        if attachment.role not in {
            DocumentRole.PURCHASE_ORDER,
            DocumentRole.GOODS_RECEIPT,
            DocumentRole.DELIVERY_NOTE,
        }:
            raise UnsupportedSupportingRoleError(attachment.role)
        run = self._get_or_create(attachment.document_id, attachment.role)
        if run.status == SupportingExtractionStatus.SUCCEEDED:
            self._record_success(attachment, run)
            self.session.commit()
            return run
        started = time.perf_counter()
        try:
            body = self.object_store.get(attachment.document.object_key)
            document_text = self.text_extractor.extract(body, attachment.document.content_type)
            output = (
                extract_purchase_order(document_text)
                if attachment.role == DocumentRole.PURCHASE_ORDER
                else extract_goods_receipt(document_text)
            )
            validated = type(output).model_validate(output)
        except (DocumentExtractionError, ValidationError) as exc:
            self.session.execute(
                update(SupportingExtractionRun)
                .where(SupportingExtractionRun.id == run.id)
                .values(
                    status=SupportingExtractionStatus.FAILED,
                    error_code=extraction_error_code(exc),
                    error_message=safe_extraction_error_message(exc),
                    completed_at=datetime.now(UTC),
                )
            )
            append_case_event(
                self.session,
                case_id=attachment.case_id,
                event_key=f"support-extraction-failed:{run.id}",
                event_type="PROCESSING_FAILED",
                stage="extraction",
                status="failed",
                message="Supporting-document extraction failed",
                document_id=attachment.document_id,
                document_role=attachment.role,
                payload={"error_code": extraction_error_code(exc)},
            )
            payable_case = self.session.get(PayableCase, attachment.case_id)
            if payable_case is not None:
                payable_case.status = CaseStatus.FAILED
                payable_case.version += 1
            self.session.commit()
            metrics.add(
                "support_extractions",
                "support_extraction",
                role=attachment.role.value,
                method="EMBEDDED_TEXT",
                status="FAILED",
            )
            metrics.add("case_events", "case", event="FAILED")
            raise
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        self.session.execute(
            update(SupportingExtractionRun)
            .where(SupportingExtractionRun.id == run.id)
            .values(
                status=SupportingExtractionStatus.SUCCEEDED,
                output_json=validated.model_dump(mode="json"),
                used_ocr=document_text.used_ocr,
                latency_ms=latency_ms,
                error_code=None,
                error_message=None,
                completed_at=datetime.now(UTC),
            )
        )
        self.session.flush()
        self.session.refresh(run)
        self._record_success(attachment, run)
        self.session.commit()
        metrics.add(
            "support_extractions",
            "support_extraction",
            role=attachment.role.value,
            method="OCR" if document_text.used_ocr else "EMBEDDED_TEXT",
            status="SUCCEEDED",
        )
        return run

    def _record_success(self, attachment: CaseDocument, run: SupportingExtractionRun) -> None:
        append_case_event(
            self.session,
            case_id=attachment.case_id,
            event_key=f"support-extraction-completed:{run.id}",
            event_type="EXTRACTION_COMPLETED",
            stage="extraction",
            status="completed",
            message="Supporting-document extraction completed; confirmation required",
            document_id=attachment.document_id,
            document_role=attachment.role,
            payload={"extraction_run_id": str(run.id), "confirmation_required": True},
        )
        payable_case = self.session.get(PayableCase, attachment.case_id)
        if (
            payable_case is not None
            and self._is_active(attachment)
            and payable_case.status
            in {
            CaseStatus.PROCESSING,
            CaseStatus.FAILED,
            }
        ):
            payable_case.status = CaseStatus.NEEDS_CONFIRMATION
            payable_case.version += 1

    def mark_operational_failure(self, attachment: CaseDocument) -> None:
        run = self._get_or_create(attachment.document_id, attachment.role)
        self.session.execute(
            update(SupportingExtractionRun)
            .where(SupportingExtractionRun.id == run.id)
            .values(
                status=SupportingExtractionStatus.FAILED,
                output_json=None,
                error_code="processing_failed",
                error_message="Supporting-document processing failed",
                completed_at=datetime.now(UTC),
            )
        )
        append_case_event(
            self.session,
            case_id=attachment.case_id,
            event_key=f"support-processing-failed:{run.id}",
            event_type="PROCESSING_FAILED",
            stage="processing",
            status="failed",
            message="Supporting-document processing failed",
            document_id=attachment.document_id,
            document_role=attachment.role,
            payload={"error_code": "processing_failed"},
        )
        payable_case = self.session.get(PayableCase, attachment.case_id)
        if (
            payable_case is not None
            and self._is_active(attachment)
            and payable_case.status != CaseStatus.FAILED
        ):
            payable_case.status = CaseStatus.FAILED
            payable_case.version += 1
        self.session.commit()
        metrics.add(
            "support_extractions",
            "support_extraction",
            role=attachment.role.value,
            method="EMBEDDED_TEXT",
            status="FAILED",
        )
        metrics.add("case_events", "case", event="FAILED")

    def _is_active(self, attachment: CaseDocument) -> bool:
        if attachment.role == DocumentRole.PURCHASE_ORDER:
            return attachment.active_slot == DocumentRole.PURCHASE_ORDER.value
        return not bool(
            self.session.scalar(
                select(exists().where(CaseDocument.supersedes_id == attachment.id))
            )
        )

    def _get_or_create(self, document_id: uuid.UUID, role: DocumentRole) -> SupportingExtractionRun:
        statement = select(SupportingExtractionRun).where(
            SupportingExtractionRun.document_id == document_id,
            SupportingExtractionRun.role == role,
            SupportingExtractionRun.extractor_name == SUPPORTING_EXTRACTOR_NAME,
            SupportingExtractionRun.extractor_version == SUPPORTING_EXTRACTOR_VERSION,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            return existing
        run = SupportingExtractionRun(
            document_id=document_id,
            role=role,
            extractor_name=SUPPORTING_EXTRACTOR_NAME,
            extractor_version=SUPPORTING_EXTRACTOR_VERSION,
            schema_version=SUPPORTING_SCHEMA_VERSION,
            status=SupportingExtractionStatus.PROCESSING,
        )
        self.session.add(run)
        try:
            self.session.commit()
            return run
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(statement)
            if concurrent is None:
                raise
            return concurrent
