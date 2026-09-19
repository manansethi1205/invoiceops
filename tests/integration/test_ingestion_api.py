import hashlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.models import Document, ExtractionRun, ExtractionRunStatus
from invoiceops.schemas.extraction import ExtractionStatus, Invoice
from tests.conftest import MemoryObjectStore, RecordingDispatcher


def test_upload_stores_document_creates_job_and_returns_status(
    client: TestClient,
    object_store: MemoryObjectStore,
    dispatcher: RecordingDispatcher,
    db_session_factory: sessionmaker[Session],
) -> None:
    response = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 synthetic", "application/pdf")},
    )

    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "queued"
    assert accepted["deduplicated"] is False
    assert accepted["job_id"] in accepted["status_url"]
    assert accepted["document_id"] in accepted["extraction_url"]
    assert dispatcher.job_ids == [accepted["job_id"]]
    assert len(object_store.objects) == 1
    with db_session_factory() as session:
        documents = list(session.scalars(select(Document)))
        assert len(documents) == 1
        assert documents[0].sha256 == hashlib.sha256(b"%PDF-1.7 synthetic").hexdigest()
    stored_body, stored_type = next(iter(object_store.objects.values()))
    assert stored_body == b"%PDF-1.7 synthetic"
    assert stored_type == "application/pdf"

    status_response = client.get(f"/v1/jobs/{accepted['job_id']}")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"

    duplicate_response = client.post(
        "/v1/invoices",
        files={"file": ("renamed.pdf", b"%PDF-1.7 synthetic", "application/pdf")},
    )
    assert duplicate_response.status_code == 202
    duplicate = duplicate_response.json()
    assert duplicate["job_id"] == accepted["job_id"]
    assert duplicate["document_id"] == accepted["document_id"]
    assert duplicate["extraction_url"] == accepted["extraction_url"]
    assert duplicate["deduplicated"] is True
    assert dispatcher.job_ids == [accepted["job_id"]]
    assert len(object_store.objects) == 1


def test_rejects_unsupported_type(client: TestClient) -> None:
    response = client.post(
        "/v1/invoices", files={"file": ("invoice.txt", b"not an invoice", "text/plain")}
    )
    assert response.status_code == 415
    assert response.json() == {"detail": "Unsupported content type: text/plain"}


def test_rejects_content_that_does_not_match_declared_type(client: TestClient) -> None:
    response = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"this is not a PDF", "application/pdf")},
    )
    assert response.status_code == 415
    assert "does not match declared type" in response.json()["detail"]


def test_rejects_empty_document(client: TestClient) -> None:
    response = client.post(
        "/v1/invoices", files={"file": ("invoice.pdf", b"", "application/pdf")}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "The uploaded file is empty"}


def test_rejects_document_over_limit(client: TestClient) -> None:
    response = client.post(
        "/v1/invoices", files={"file": ("invoice.pdf", b"x" * 1025, "application/pdf")}
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "The uploaded file exceeds 1024 bytes"}


def test_missing_job_is_404(client: TestClient) -> None:
    response = client.get("/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_unknown_document_extraction_is_404(client: TestClient) -> None:
    response = client.get(
        "/v1/invoices/00000000-0000-0000-0000-000000000000/extraction"
    )
    assert response.status_code == 404


def test_existing_document_without_run_returns_processing(
    client: TestClient,
) -> None:
    upload = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 pending", "application/pdf")},
    ).json()

    response = client.get(upload["extraction_url"])

    assert response.status_code == 202
    assert response.json() == {
        "document_id": upload["document_id"],
        "status": "processing",
    }


def missing_invoice() -> Invoice:
    from invoiceops.schemas.extraction import ExtractedField

    missing = {"value": None, "status": ExtractionStatus.MISSING, "evidence": []}
    return Invoice(
        invoice_number=ExtractedField[str](**missing),
        invoice_date=ExtractedField(**missing),
        currency=ExtractedField[str](**missing),
        subtotal=ExtractedField(**missing),
        tax=ExtractedField(**missing),
        total=ExtractedField(**missing),
        line_items=[],
    )


def test_completed_extraction_returns_typed_result_without_storage_details(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    upload = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 completed", "application/pdf")},
    ).json()
    with db_session_factory() as session:
        session.add(
            ExtractionRun(
                document_id=uuid.UUID(upload["document_id"]),
                extractor_name="deterministic-baseline",
                extractor_version="0.1.0",
                schema_version="invoice-v1",
                status=ExtractionRunStatus.SUCCEEDED,
                output_json=missing_invoice().model_dump(mode="json"),
                used_ocr=False,
                latency_ms=4.25,
            )
        )
        session.commit()

    response = client.get(upload["extraction_url"])

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["invoice"]["invoice_number"]["status"] == "missing"
    assert body["extractor"]["schema_version"] == "invoice-v1"
    assert "object_key" not in response.text
    assert "bucket" not in response.text


def test_failed_extraction_returns_only_safe_failure_state(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    upload = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 failed", "application/pdf")},
    ).json()
    with db_session_factory() as session:
        session.add(
            ExtractionRun(
                document_id=uuid.UUID(upload["document_id"]),
                extractor_name="deterministic-baseline",
                extractor_version="0.1.0",
                schema_version="invoice-v1",
                status=ExtractionRunStatus.FAILED,
                error_code="document_unreadable",
                error_message="internal safe message",
            )
        )
        session.commit()

    response = client.get(upload["extraction_url"])

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "document_unreadable"
    assert response.json()["invoice"] is None
    assert "internal safe message" not in response.text
