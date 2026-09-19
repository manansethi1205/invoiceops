import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from invoiceops.db import Base
from invoiceops.extraction.errors import UnreadableDocumentError
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.service import ExtractionService
from invoiceops.models import Document, ExtractionRun, ExtractionRunStatus
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    Invoice,
)
from tests.conftest import MemoryObjectStore
from tests.unit.test_header_pipeline import generated_invoice_pdf


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def missing_field[T]() -> ExtractedField[T]:
    return ExtractedField[T](value=None, status=ExtractionStatus.MISSING, evidence=[])


def empty_invoice() -> Invoice:
    return Invoice(
        invoice_number=missing_field(),
        invoice_date=missing_field(),
        currency=missing_field(),
        subtotal=missing_field(),
        tax=missing_field(),
        total=missing_field(),
        line_items=[],
    )


def create_document(
    session: Session,
    store: MemoryObjectStore,
    body: bytes = b"synthetic",
) -> Document:
    document = Document(
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=len(body),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        object_key=f"invoices/{uuid.uuid4()}/synthetic.pdf",
    )
    store.put(document.object_key, body, document.content_type)
    session.add(document)
    session.commit()
    return document


class FakeTextExtractor:
    def __init__(self, *, used_ocr: bool = True) -> None:
        self.used_ocr = used_ocr
        self.calls = 0

    def extract(self, body: bytes, content_type: str) -> DocumentText:
        self.calls += 1
        assert body
        assert content_type == "application/pdf"
        return DocumentText(pages=[], used_ocr=self.used_ocr)


class FakeInvoiceExtractor:
    name = "deterministic-baseline"

    def __init__(self, *, version: str = "0.1.0") -> None:
        self.version = version
        self.calls = 0

    def extract(self, document: DocumentText) -> Invoice:
        self.calls += 1
        return empty_invoice()


class FailingTextExtractor:
    def extract(self, body: bytes, content_type: str) -> DocumentText:
        raise UnreadableDocumentError(f"could not decode secret bytes: {body!r}")


def test_success_is_persisted_and_second_call_is_a_noop() -> None:
    with make_session() as session:
        store = MemoryObjectStore()
        document = create_document(session, store)
        text_extractor = FakeTextExtractor(used_ocr=True)
        invoice_extractor = FakeInvoiceExtractor()
        service = ExtractionService(session, store, text_extractor, invoice_extractor)

        first = service.process(document)
        second = service.process(document)

        assert second.id == first.id
        assert first.status == ExtractionRunStatus.SUCCEEDED
        assert first.used_ocr is True
        assert first.latency_ms is not None and first.latency_ms >= 0
        assert first.output_json is not None
        Invoice.model_validate(first.output_json)
        assert text_extractor.calls == 1
        assert invoice_extractor.calls == 1
        assert session.scalar(select(func.count()).select_from(ExtractionRun)) == 1


def test_terminal_failure_stores_only_safe_error_details() -> None:
    with make_session() as session:
        store = MemoryObjectStore()
        document = create_document(session, store, b"raw confidential content")
        service = ExtractionService(
            session,
            store,
            FailingTextExtractor(),
            FakeInvoiceExtractor(),
        )

        with pytest.raises(UnreadableDocumentError):
            service.process(document)

        run = session.scalar(select(ExtractionRun))
        assert run is not None
        assert run.status == ExtractionRunStatus.FAILED
        assert run.error_code == "document_unreadable"
        assert run.error_message == "The document could not be read"
        assert "confidential" not in run.error_message
        assert run.output_json is None


def test_new_extractor_version_creates_a_separate_run() -> None:
    with make_session() as session:
        store = MemoryObjectStore()
        document = create_document(session, store)

        first = ExtractionService(
            session, store, FakeTextExtractor(), FakeInvoiceExtractor(version="0.1.0")
        ).process(document)
        second = ExtractionService(
            session, store, FakeTextExtractor(), FakeInvoiceExtractor(version="0.2.0")
        ).process(document)

        assert first.id != second.id
        assert session.scalar(select(func.count()).select_from(ExtractionRun)) == 2


def test_database_constraint_rejects_duplicate_version_rows() -> None:
    with make_session() as session:
        store = MemoryObjectStore()
        document = create_document(session, store)
        session.add_all(
            [
                ExtractionRun(
                    document_id=document.id,
                    extractor_name="deterministic-baseline",
                    extractor_version="0.1.0",
                    schema_version="invoice-v1",
                ),
                ExtractionRun(
                    document_id=document.id,
                    extractor_name="deterministic-baseline",
                    extractor_version="0.1.0",
                    schema_version="invoice-v1",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_real_generated_pdf_is_persisted_as_typed_invoice() -> None:
    with make_session() as session:
        store = MemoryObjectStore()
        document = create_document(session, store, generated_invoice_pdf())
        run = ExtractionService(
            session,
            store,
            DocumentTextExtractor(),
            DeterministicInvoiceExtractor(),
        ).process(document)

        invoice = Invoice.model_validate(run.output_json)
        assert invoice.invoice_number.value == "SYN-12345"
        assert invoice.invoice_date.value == date(2026, 9, 19)
        assert invoice.currency.value == "INR"
        assert invoice.subtotal.value == Decimal("1000.00")
        assert invoice.tax.value == Decimal("180.00")
        assert invoice.total.value == Decimal("1180.00")
