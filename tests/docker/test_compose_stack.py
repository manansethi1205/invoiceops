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
        page = document.new_page(width=400, height=300)
        page.insert_textbox(
            pymupdf.Rect(30, 30, 370, 270),
            (
                f"Synthetic invoice number {invoice_number} vendor Example Components "
                "currency INR subtotal 1000 tax 180 total 1180"
            ),
            fontsize=11,
        )
        return document.tobytes()
    finally:
        document.close()


def test_real_stack_upload_is_idempotent_and_worker_completes() -> None:
    base_url = os.environ["API_BASE_URL"]
    body = synthetic_pdf_bytes(f"SYN-{uuid.uuid4()}")
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

        job = wait_for_terminal_status(client, first["status_url"])
        assert job["status"] == "succeeded"


def test_real_stack_returns_clear_invalid_file_error() -> None:
    base_url = os.environ["API_BASE_URL"]
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(
            "/v1/invoices",
            files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
        )
    assert response.status_code == 415
    assert "does not match declared type application/pdf" in response.json()["detail"]
