import os
import time
import uuid

import httpx
import pymupdf
import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        "API_BASE_URL" not in os.environ,
        reason="Run through the Docker Compose integration-tests service",
    ),
]


def wait_for_terminal_status(client: httpx.Client, status_url: str) -> dict[str, object]:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(status_url)
        response.raise_for_status()
        job = response.json()
        if job["status"] in {"succeeded", "failed"}:
            return job
        time.sleep(0.25)
    pytest.fail("job did not reach a terminal state within 20 seconds")


def synthetic_pdf_bytes(invoice_number: str) -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        lines = [
            "SYNTHETIC INVOICE - DEMO DATA ONLY",
            f"Invoice Number: {invoice_number}",
            "Invoice Date: 19/09/2026",
            "Currency: INR",
            "Subtotal: 1,000.00",
            "GST 18%: 180.00",
            "Grand Total: INR 1,180.00",
        ]
        for index, line in enumerate(lines):
            page.insert_text((72, 72 + index * 30), line, fontsize=12)
        return document.tobytes()
    finally:
        document.close()


def test_real_stack_upload_is_idempotent_and_worker_completes() -> None:
    base_url = os.environ["API_BASE_URL"]
    invoice_number = f"SYN-{uuid.uuid4()}"
    body = synthetic_pdf_bytes(invoice_number)
    with httpx.Client(base_url=base_url, timeout=10) as client:
        first_response = client.post(
            "/v1/invoices", files={"file": ("compose.pdf", body, "application/pdf")}
        )
        first_response.raise_for_status()
        first = first_response.json()
        assert first["deduplicated"] is False

        duplicate_response = client.post(
            "/v1/invoices", files={"file": ("renamed.pdf", body, "application/pdf")}
        )
        duplicate_response.raise_for_status()
        duplicate = duplicate_response.json()
        assert duplicate["deduplicated"] is True
        assert duplicate["job_id"] == first["job_id"]
        assert duplicate["document_id"] == first["document_id"]
        assert duplicate["extraction_url"] == first["extraction_url"]

        job = wait_for_terminal_status(client, first["status_url"])
        assert job["status"] == "succeeded"
        extraction_response = client.get(first["extraction_url"])
        extraction_response.raise_for_status()
        extraction = extraction_response.json()
        assert extraction["status"] == "succeeded"
        invoice = extraction["invoice"]
        assert invoice["invoice_number"]["value"] == invoice_number
        assert invoice["currency"]["value"] == "INR"
        assert invoice["subtotal"]["value"] == "1000.00"
        assert invoice["tax"]["value"] == "180.00"
        assert invoice["total"]["value"] == "1180.00"
        duplicate_extraction = client.get(duplicate["extraction_url"])
        duplicate_extraction.raise_for_status()
        assert duplicate_extraction.json()["created_at"] == extraction["created_at"]


def test_real_stack_returns_clear_invalid_file_error() -> None:
    base_url = os.environ["API_BASE_URL"]
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(
            "/v1/invoices",
            files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
        )
    assert response.status_code == 415
    assert "does not match declared type application/pdf" in response.json()["detail"]
