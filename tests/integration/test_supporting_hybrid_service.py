import uuid

import fitz
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.extraction.hybrid.provider import (
    VisionProviderSchemaError,
    VisionProviderTransientError,
)
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.supporting_hybrid import (
    DELIVERY_PROMPT_VERSION,
    SUPPORTING_HYBRID_NAME,
    DeliveryNoteCandidate,
    SupportingResponse,
)
from invoiceops.extraction.supporting_hybrid_service import HybridSupportingExtractionService
from invoiceops.extraction.supporting_provider import FakeSupportingVisionProvider
from invoiceops.extraction.supporting_service import SupportingExtractionService
from invoiceops.models import (
    CaseDocument,
    Document,
    ModelCallStatus,
    PayableCase,
    SupportingExtractionRun,
    SupportingModelCall,
)
from invoiceops.schemas.cases import (
    CaseStatus,
    DocumentRole,
    ExtractedGoodsReceipt,
    ExtractedPurchaseOrder,
    SupportingExtractionStatus,
)
from tests.conftest import MemoryObjectStore
from tests.unit.test_supporting_extraction import document_from_rows
from tests.unit.test_supporting_hybrid import field, po_candidate


class FixedTextExtractor:
    def __init__(self) -> None:
        self.document = document_from_rows([[("Reference", 0.05), ("ABC-100", 0.3)]])

    def extract(self, body: bytes, content_type: str):  # type: ignore[no-untyped-def]
        del body, content_type
        return self.document


def attachment(
    session: Session, store: MemoryObjectStore,
    role: DocumentRole = DocumentRole.PURCHASE_ORDER,
) -> CaseDocument:
    pdf = fitz.open()
    pdf.new_page().insert_text((72, 72), "Reference ABC-100")
    body = pdf.tobytes()
    pdf.close()
    document = Document(
        original_filename="synthetic-po.pdf",
        content_type="application/pdf",
        byte_size=len(body),
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        object_key=f"supporting/{uuid.uuid4()}.pdf",
    )
    store.put(document.object_key, body, document.content_type)
    payable_case = PayableCase(
        case_number=f"CASE-{uuid.uuid4().hex[:12]}",
        status=CaseStatus.PROCESSING,
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="a" * 64,
    )
    session.add_all([document, payable_case])
    session.flush()
    item = CaseDocument(
        case_id=payable_case.id,
        document_id=document.id,
        role=role,
        attachment_order=1,
        active_slot=role.value,
        idempotency_key=uuid.uuid4().hex,
        request_fingerprint="b" * 64,
    )
    session.add(item)
    session.commit()
    return item


def service(
    session: Session, store: MemoryObjectStore, provider: FakeSupportingVisionProvider
) -> HybridSupportingExtractionService:
    text = FixedTextExtractor()
    baseline = SupportingExtractionService(session, store, text)
    return HybridSupportingExtractionService(
        session=session,
        object_store=store,
        text_extractor=text,
        baseline_service=baseline,
        renderer=PageRenderer(),
        provider_factory=lambda: provider,
        provider_name="fake",
        requested_model="fake-supporting",
    )


def test_hybrid_persists_separate_baseline_call_and_idempotent_result(
    db_session_factory: sessionmaker[Session],
    object_store: MemoryObjectStore,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store)
        provider = FakeSupportingVisionProvider(
            SupportingResponse(
                candidate=po_candidate(po_number=field("ABC-100")),
                latency_ms=5,
            )
        )
        runner = service(session, object_store, provider)
        first = runner.process(item)
        repeated = runner.process(item)
        assert repeated.id == first.id
        assert first.extractor_name == SUPPORTING_HYBRID_NAME
        assert provider.calls == 1
        assert session.scalar(select(func.count()).select_from(SupportingExtractionRun)) == 2
        assert session.scalar(select(func.count()).select_from(SupportingModelCall)) == 1
        baseline = session.scalar(
            select(SupportingExtractionRun).where(
                SupportingExtractionRun.extractor_name == "deterministic-supporting-documents"
            )
        )
        assert baseline is not None and baseline.output_json is not None
        assert ExtractedPurchaseOrder.model_validate(baseline.output_json).po_number.value is None
        assert first.output_json is not None
        assert ExtractedPurchaseOrder.model_validate(first.output_json).po_number.value == "ABC-100"
        call = session.scalar(select(SupportingModelCall))
        assert call is not None and call.status == ModelCallStatus.SUCCEEDED
        assert call.input_document_hash == item.document.sha256
        assert call.candidate_json is not None
        assert call.grounding_json is not None
        assert session.get(PayableCase, item.case_id).status == CaseStatus.NEEDS_CONFIRMATION


def test_provider_timeout_or_malformed_json_abstains_and_retry_does_not_call_again(
    db_session_factory: sessionmaker[Session],
    object_store: MemoryObjectStore,
) -> None:
    for error in (
        VisionProviderTransientError("timeout"),
        VisionProviderSchemaError("malformed json"),
    ):
        with db_session_factory() as session:
            item = attachment(session, object_store)
            provider = FakeSupportingVisionProvider(error=error)
            runner = service(session, object_store, provider)
            first = runner.process(item)
            second = runner.process(item)
            assert first.id == second.id
            assert provider.calls == 1
            assert first.output_json is not None
            assert ExtractedPurchaseOrder.model_validate(first.output_json).po_number.value is None
            call = session.scalar(
                select(SupportingModelCall).where(SupportingModelCall.supporting_run_id == first.id)
            )
            assert call is not None and call.status == ModelCallStatus.FAILED
            assert call.error_code == error.code
            assert call.candidate_json is None


def test_api_selects_successful_hybrid_run_without_canonical_record(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    object_store: MemoryObjectStore,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store)
        provider = FakeSupportingVisionProvider(
            SupportingResponse(candidate=po_candidate(po_number=field("ABC-100")), latency_ms=1)
        )
        run = service(session, object_store, provider).process(item)
        case_id = item.case_id
        document_id = item.document_id
    response = client.get(f"/v1/cases/{case_id}/extractions")
    assert response.status_code == 200
    result = response.json()
    assert len(result) == 1
    assert result[0]["id"] == str(run.id)
    assert result[0]["document_id"] == str(document_id)
    assert result[0]["output"]["po_number"]["value"] == "ABC-100"
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(SupportingModelCall)) == 1
        from invoiceops.models import CaseConfirmation, PurchaseOrder

        assert session.scalar(select(func.count()).select_from(CaseConfirmation)) == 0
        assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0


def test_delivery_note_uses_distinct_prompt_and_receipt_confirmation_schema(
    db_session_factory: sessionmaker[Session], object_store: MemoryObjectStore,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store, DocumentRole.DELIVERY_NOTE)
        empty = field()
        candidate = DeliveryNoteCandidate(
            receipt_number=field("ABC-100"), referenced_po_number=empty,
            received_date=empty, supplier=empty, line_items=[],
        )
        provider = FakeSupportingVisionProvider(
            SupportingResponse(candidate=candidate, latency_ms=1)
        )
        run = service(session, object_store, provider).process(item)
        assert run.output_json is not None
        receipt = ExtractedGoodsReceipt.model_validate(run.output_json)
        assert receipt.receipt_number.value == "ABC-100"
        call = session.scalar(select(SupportingModelCall).where(
            SupportingModelCall.supporting_run_id == run.id
        ))
        assert call is not None and call.prompt_version == DELIVERY_PROMPT_VERSION


def test_processing_call_can_resume_without_creating_another_row(
    db_session_factory: sessionmaker[Session], object_store: MemoryObjectStore,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store)
        first_provider = FakeSupportingVisionProvider(error=VisionProviderTransientError("outage"))
        first = service(session, object_store, first_provider).process(item)
        call = session.scalar(select(SupportingModelCall))
        assert call is not None
        # Simulate a worker crash before an invocation result was committed.
        first.status = SupportingExtractionStatus.PROCESSING
        call.status = ModelCallStatus.PROCESSING
        call.error_code = None
        session.commit()
        replay_provider = FakeSupportingVisionProvider(
            SupportingResponse(candidate=po_candidate(po_number=field("ABC-100")), latency_ms=1)
        )
        resumed = service(session, object_store, replay_provider).process(item)
        assert resumed.id == first.id
        assert replay_provider.calls == 1
        assert session.scalar(select(func.count()).select_from(SupportingModelCall)) == 1


def test_corrupt_stored_candidate_abstains_on_replay(
    db_session_factory: sessionmaker[Session], object_store: MemoryObjectStore,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store)
        provider = FakeSupportingVisionProvider(
            SupportingResponse(candidate=po_candidate(po_number=field("ABC-100")), latency_ms=1)
        )
        first = service(session, object_store, provider).process(item)
        call = session.scalar(select(SupportingModelCall))
        assert call is not None
        first.status = SupportingExtractionStatus.PROCESSING
        call.candidate_json = {"malformed": True}
        session.commit()
        resumed = service(session, object_store, provider).process(item)
        assert provider.calls == 1
        assert resumed.output_json is not None
        assert ExtractedPurchaseOrder.model_validate(resumed.output_json).po_number.value is None
