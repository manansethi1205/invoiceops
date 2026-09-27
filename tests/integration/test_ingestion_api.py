import hashlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.jobs.events import append_job_event
from invoiceops.models import (
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    IngestionJob,
    JobEvent,
    JobStatus,
    ModelCall,
    ModelCallStatus,
)
from invoiceops.observability.metrics import metrics
from invoiceops.schemas.extraction import ExtractionStatus, Invoice
from invoiceops.schemas.jobs import JobEventType
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
    assert accepted["job_id"] in accepted["events_url"]
    assert accepted["document_id"] in accepted["extraction_url"]
    assert dispatcher.job_ids == [accepted["job_id"]]
    assert len(object_store.objects) == 1
    with db_session_factory() as session:
        documents = list(session.scalars(select(Document)))
        assert len(documents) == 1
        assert documents[0].sha256 == hashlib.sha256(b"%PDF-1.7 synthetic").hexdigest()
        events = list(session.scalars(select(JobEvent).order_by(JobEvent.sequence_number)))
        assert [event.event_type for event in events] == [
            JobEventType.UPLOAD_ACCEPTED.value,
            JobEventType.DOCUMENT_VALIDATED.value,
        ]
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


def test_upload_commits_when_metric_recorder_raises(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenCounter:
        def add(self, value: int, labels: dict[str, object]) -> None:
            del value, labels
            raise RuntimeError("synthetic metric failure")

    metrics.initialize()
    monkeypatch.setattr(metrics, "ingestion", BrokenCounter())
    response = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 fail-open", "application/pdf")},
    )

    assert response.status_code == 202
    with db_session_factory() as session:
        assert len(list(session.scalars(select(Document)))) == 1


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


def test_job_event_stream_replays_from_last_event_id_and_closes_at_terminal(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    accepted = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 event-stream", "application/pdf")},
    ).json()
    job_id = uuid.UUID(accepted["job_id"])
    with db_session_factory() as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None
        job.status = JobStatus.SUCCEEDED
        append_job_event(
            session,
            job_id=job_id,
            event_key="processing.completed",
            event_type=JobEventType.PROCESSING_COMPLETED,
            stage="processing",
            status="completed",
            message="Invoice processing completed",
        )
        session.commit()

    response = client.get(f"/v1/jobs/{job_id}/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 1\nevent: upload.accepted" in response.text
    assert "id: 2\nevent: document.validated" in response.text
    assert "id: 3\nevent: processing.completed" in response.text
    assert "event-stream" not in response.text

    resumed = client.get(
        f"/v1/jobs/{job_id}/events",
        headers={"Last-Event-ID": "2"},
    )
    assert resumed.status_code == 200
    assert "id: 1" not in resumed.text
    assert "id: 2" not in resumed.text
    assert "id: 3\nevent: processing.completed" in resumed.text


def test_job_event_stream_rejects_invalid_cursor(client: TestClient) -> None:
    accepted = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 bad-cursor", "application/pdf")},
    ).json()

    response = client.get(
        f"/v1/jobs/{accepted['job_id']}/events",
        headers={"Last-Event-ID": "not-a-number"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Last-Event-ID must be an integer"}


def test_console_reads_invoice_content_and_measured_dashboard_counts(
    client: TestClient,
) -> None:
    body = b"%PDF-1.7 console-content"
    accepted = client.post(
        "/v1/invoices",
        files={"file": ("console.pdf", body, "application/pdf")},
    ).json()

    index = client.get("/v1/invoices")
    detail = client.get(f"/v1/invoices/{accepted['document_id']}")
    content = client.get(f"/v1/documents/{accepted['document_id']}/content")
    dashboard = client.get("/v1/dashboard/summary")

    assert index.status_code == 200
    assert index.json()["items"][0]["document_id"] == accepted["document_id"]
    assert index.json()["items"][0]["invoice_number"] is None
    assert detail.status_code == 200
    assert detail.json()["filename"] == "console.pdf"
    assert content.status_code == 200
    assert content.content == body
    assert content.headers["cache-control"] == "private, no-store"
    assert content.headers["content-disposition"] == "inline"
    assert dashboard.status_code == 200
    assert dashboard.json() == {
        "documents_total": 1,
        "jobs_processing": 1,
        "jobs_failed": 0,
        "reviews_waiting": 0,
        "oldest_waiting_review_opened_at": None,
    }


def test_document_content_failure_is_sanitized(
    client: TestClient,
    object_store: MemoryObjectStore,
) -> None:
    accepted = client.post(
        "/v1/invoices",
        files={"file": ("missing.pdf", b"%PDF-1.7 missing-object", "application/pdf")},
    ).json()
    object_store.objects.clear()

    response = client.get(f"/v1/documents/{accepted['document_id']}/content")

    assert response.status_code == 503
    assert response.json() == {"detail": "Document is temporarily unavailable"}
    assert "object_key" not in response.text


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
                extractor_version="0.2.0",
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
                extractor_version="0.2.0",
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


def test_current_extraction_prefers_hybrid_and_exposes_only_safe_lineage(
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    upload = client.post(
        "/v1/invoices",
        files={"file": ("invoice.pdf", b"%PDF-1.7 hybrid", "application/pdf")},
    ).json()
    with db_session_factory() as session:
        document_id = uuid.UUID(upload["document_id"])
        baseline = ExtractionRun(
            document_id=document_id,
            extractor_name="deterministic-baseline",
            extractor_version="0.2.0",
            schema_version="invoice-v1",
            status=ExtractionRunStatus.SUCCEEDED,
            output_json=missing_invoice().model_dump(mode="json"),
        )
        hybrid = ExtractionRun(
            document_id=document_id,
            extractor_name="hybrid-routed",
            extractor_version="0.3.0",
            schema_version="invoice-v1",
            status=ExtractionRunStatus.SUCCEEDED,
            output_json=missing_invoice().model_dump(mode="json"),
        )
        session.add_all([baseline, hybrid])
        session.flush()
        session.add(
            ModelCall(
                extraction_run_id=hybrid.id,
                provider="fake",
                requested_model="fake-vision",
                returned_model="fake-returned",
                prompt_version="invoice-vision-v1",
                status=ModelCallStatus.FAILED,
                request_fingerprint="a" * 64,
                routing_json={"reasons": ["CRITICAL_FIELD_MISSING"]},
                grounding_fusion_json={"grounding": {}, "fusion": {}},
                error_code="provider_transient_error",
            )
        )
        session.commit()

    response = client.get(upload["extraction_url"])
    body = response.json()
    assert response.status_code == 200
    assert body["extractor"]["name"] == "hybrid-routed"
    assert body["hybrid"]["routing_reasons"] == ["CRITICAL_FIELD_MISSING"]
    assert body["hybrid"]["provider_failure_code"] == "provider_transient_error"
    assert "request_fingerprint" not in response.text
    assert "candidate_json" not in response.text
    assert "a" * 64 not in response.text
