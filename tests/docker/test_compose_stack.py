import os
import time
import uuid

import httpx
import pytest

from tests.synthetic_documents import generated_invoice_pdf

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


def test_real_stack_upload_is_idempotent_and_worker_completes() -> None:
    base_url = os.environ["API_BASE_URL"]
    invoice_number = f"SYN-{uuid.uuid4()}"
    body = generated_invoice_pdf(invoice_number)
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
        assert invoice["subtotal"]["value"] == "1200.00"
        assert invoice["tax"]["value"] == "216.00"
        assert invoice["total"]["value"] == "1416.00"
        assert len(invoice["line_items"]) == 2
        first_item, second_item = invoice["line_items"]
        assert first_item["description"]["value"] == "Industrial Filter"
        assert first_item["quantity"]["value"] == "2"
        assert first_item["unit_price"]["value"] == "500.00"
        assert first_item["line_total"]["value"] == "1000.00"
        assert second_item["description"]["value"] == "Mounting Bracket"
        assert second_item["quantity"]["value"] == "4"
        assert second_item["unit_price"]["value"] == "50.00"
        assert second_item["line_total"]["value"] == "200.00"
        for item in invoice["line_items"]:
            for field in item.values():
                assert field["evidence"]
                bbox = field["evidence"][0]["bbox"]
                assert 0 <= bbox["x0"] <= bbox["x1"] <= 1
                assert 0 <= bbox["y0"] <= bbox["y1"] <= 1
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
