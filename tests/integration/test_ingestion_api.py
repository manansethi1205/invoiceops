import hashlib

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.models import Document
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
