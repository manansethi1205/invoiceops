import uuid

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from invoiceops.db import Base
from invoiceops.extraction.hybrid.provider import (
    FakeVisionExtractionProvider,
    VisionProviderTransientError,
)
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.hybrid.schemas import (
    CandidateField,
    VisionExtractionResponse,
    VisionInvoiceCandidate,
    VisionUsage,
)
from invoiceops.extraction.hybrid.service import HybridExtractionService
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.service import ExtractionService
from invoiceops.models import (
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    ModelCall,
    ModelCallStatus,
)
from invoiceops.schemas.extraction import DocumentText, ExtractedField, ExtractionStatus, Invoice
from tests.conftest import MemoryObjectStore
from tests.synthetic_documents import generated_invoice_pdf


def session() -> Session:
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def document(db: Session, store: MemoryObjectStore, body: bytes) -> Document:
    item = Document(
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=len(body),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        object_key=f"invoices/{uuid.uuid4()}/synthetic.pdf",
    )
    store.put(item.object_key, body, item.content_type)
    db.add(item)
    db.commit()
    return item


def missing() -> CandidateField:
    return CandidateField(raw_value=None, page=None, evidence_quote=None, confidence=None)


def vision_candidate() -> VisionInvoiceCandidate:
    empty = missing()
    return VisionInvoiceCandidate(
        invoice_number=CandidateField(
            raw_value="SYN-12345", page=0, evidence_quote="SYN-12345", confidence=0.9
        ),
        invoice_date=empty,
        currency=empty,
        subtotal=empty,
        tax=empty,
        total=empty,
        line_items=[],
    )


def empty_invoice() -> Invoice:
    field = ExtractedField[object](value=None, status=ExtractionStatus.MISSING, evidence=[])
    return Invoice(
        invoice_number=field,
        invoice_date=field,
        currency=field,
        subtotal=field,
        tax=field,
        total=field,
        line_items=[],
    )


class EmptyExtractor:
    name = "deterministic-baseline"
    version = "0.2.0"

    def extract(self, document: DocumentText) -> Invoice:
        return empty_invoice()


def hybrid_service(
    db: Session,
    store: MemoryObjectStore,
    provider: FakeVisionExtractionProvider,
    *,
    complete_baseline: bool,
    factory_calls: list[int],
) -> HybridExtractionService:
    text = DocumentTextExtractor()
    baseline = ExtractionService(
        db,
        store,
        text,
        DeterministicInvoiceExtractor() if complete_baseline else EmptyExtractor(),
    )

    def factory() -> FakeVisionExtractionProvider:
        factory_calls.append(1)
        return provider

    return HybridExtractionService(
        session=db,
        object_store=store,
        text_extractor=text,
        baseline_service=baseline,
        renderer=PageRenderer(max_pages=2),
        provider_factory=factory,
        provider_name=provider.name,
        requested_model=provider.requested_model,
        prompt_version="invoice-vision-v1",
    )


def test_router_decline_persists_separate_run_without_initializing_provider() -> None:
    with session() as db:
        store = MemoryObjectStore()
        item = document(db, store, generated_invoice_pdf())
        provider = FakeVisionExtractionProvider()
        factory_calls: list[int] = []
        run = hybrid_service(
            db, store, provider, complete_baseline=True, factory_calls=factory_calls
        ).process(item)
        assert run.extractor_name == "hybrid-routed"
        assert run.extractor_version == "0.3.0"
        assert run.status == ExtractionRunStatus.SUCCEEDED
        assert factory_calls == []
        assert provider.calls == 0
        assert db.scalar(select(func.count()).select_from(ExtractionRun)) == 2
        call = db.scalar(select(ModelCall))
        assert call is not None and call.status == ModelCallStatus.SKIPPED


def test_invocation_lineage_is_idempotent_and_records_tokens() -> None:
    with session() as db:
        store = MemoryObjectStore()
        item = document(db, store, generated_invoice_pdf())
        response = VisionExtractionResponse(
            candidate=vision_candidate(),
            response_id="resp-test",
            returned_model="fake-returned",
            usage=VisionUsage(input_tokens=12, output_tokens=5, total_tokens=17),
            latency_ms=8.5,
        )
        provider = FakeVisionExtractionProvider(response=response)
        factory_calls: list[int] = []
        service = hybrid_service(
            db, store, provider, complete_baseline=False, factory_calls=factory_calls
        )
        first = service.process(item)
        second = service.process(item)
        assert first.id == second.id
        assert provider.calls == 1
        assert db.scalar(select(func.count()).select_from(ModelCall)) == 1
        call = db.scalar(select(ModelCall))
        assert call is not None
        assert call.status == ModelCallStatus.SUCCEEDED
        assert call.provider_response_id == "resp-test"
        assert (call.input_tokens, call.output_tokens, call.total_tokens) == (12, 5, 17)
        invoice = Invoice.model_validate(first.output_json)
        assert invoice.invoice_number.value == "SYN-12345"
        assert invoice.invoice_number.evidence


def test_provider_failure_preserves_deterministic_output_without_document_content() -> None:
    with session() as db:
        store = MemoryObjectStore()
        item = document(db, store, generated_invoice_pdf())
        provider = FakeVisionExtractionProvider(
            error=VisionProviderTransientError("secret invoice value SYN-12345")
        )
        service = hybrid_service(db, store, provider, complete_baseline=False, factory_calls=[])
        run = service.process(item)
        assert run.status == ExtractionRunStatus.SUCCEEDED
        assert (
            Invoice.model_validate(run.output_json).invoice_number.status
            == ExtractionStatus.MISSING
        )
        call = db.scalar(select(ModelCall))
        assert call is not None
        assert call.status == ModelCallStatus.FAILED
        assert call.error_code == "provider_transient_error"
        assert "SYN-12345" not in str(call.error_code)
