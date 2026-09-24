import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import httpx
import pytest

from tests.synthetic_documents import generated_incomplete_invoice_pdf, generated_invoice_pdf

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
            return cast(dict[str, object], job)
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
        expected_strategy = os.environ.get("EXPECT_EXTRACTION_STRATEGY")
        if expected_strategy:
            assert extraction["extractor"]["name"] == expected_strategy
            assert extraction["hybrid"]["strategy"] == "hybrid-routed@0.3.0"
            assert extraction["hybrid"]["provider_invoked"] is False
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

        po_response = client.post(
            "/v1/purchase-orders",
            json={
                "external_po_number": f"PO-{invoice_number}",
                "vendor_name": "Synthetic Compose Vendor",
                "currency": "INR",
                "lines": [
                    {
                        "line_number": "1",
                        "description": "Industrial Filter",
                        "ordered_quantity": "2",
                        "unit_price": "500.00",
                    },
                    {
                        "line_number": "2",
                        "description": "Mounting Bracket",
                        "ordered_quantity": "4",
                        "unit_price": "50.00",
                    },
                ],
            },
        )
        po_response.raise_for_status()
        purchase_order = po_response.json()
        match_path = f"/v1/documents/{first['document_id']}/matches"
        match_response = client.post(
            match_path, json={"purchase_order_id": purchase_order["id"]}
        )
        assert match_response.status_code == 201
        match = match_response.json()
        assert match["decision"] == "MATCHED"
        assert match["policy_version"] == "matching-v1"
        assert len(match["result"]["line_assignments"]) == 2
        repeated_match = client.post(
            match_path, json={"purchase_order_id": purchase_order["id"]}
        )
        assert repeated_match.status_code == 200
        assert repeated_match.json()["id"] == match["id"]
        fetched_match = client.get(f"/v1/matches/{match['id']}")
        fetched_match.raise_for_status()
        assert fetched_match.json() == match

        reencoded_body = generated_invoice_pdf(invoice_number, producer="synthetic-reexport")
        assert reencoded_body != body
        reencoded_response = client.post(
            "/v1/invoices",
            files={"file": ("reencoded.pdf", reencoded_body, "application/pdf")},
        )
        reencoded_response.raise_for_status()
        reencoded = reencoded_response.json()
        assert reencoded["deduplicated"] is False
        assert reencoded["document_id"] != first["document_id"]
        assert wait_for_terminal_status(client, reencoded["status_url"])["status"] == "succeeded"

        concurrency_po_response = client.post(
            "/v1/purchase-orders",
            json={
                "external_po_number": f"PO-RECEIPT-{invoice_number}",
                "vendor_name": "Synthetic Compose Vendor",
                "currency": "INR",
                "lines": purchase_order["lines"],
            },
        )
        concurrency_po_response.raise_for_status()
        concurrency_po = concurrency_po_response.json()
        receipt_response = client.post(
            "/v1/goods-receipts",
            json={
                "purchase_order_id": concurrency_po["id"],
                "external_receipt_number": f"GRN-{invoice_number}",
                "received_at": "2026-09-18T12:00:00Z",
                "lines": [
                    {
                        "purchase_order_line_id": line["id"],
                        "accepted_quantity": line["ordered_quantity"],
                    }
                    for line in concurrency_po["lines"]
                ],
            },
        )
        receipt_response.raise_for_status()

        def concurrent_match(document_id: str) -> dict[str, object]:
            with httpx.Client(base_url=base_url, timeout=20) as concurrent_client:
                response = concurrent_client.post(
                    f"/v1/documents/{document_id}/matches",
                    json={
                        "purchase_order_id": concurrency_po["id"],
                        "mode": "THREE_WAY",
                    },
                )
                response.raise_for_status()
                return cast(dict[str, object], response.json())

        with ThreadPoolExecutor(max_workers=2) as executor:
            concurrent_results = list(
                executor.map(concurrent_match, [first["document_id"], reencoded["document_id"]])
            )
        assert sorted(item["decision"] for item in concurrent_results) == [
            "MATCHED",
            "NEEDS_REVIEW",
        ]
        reviewed = next(
            item for item in concurrent_results if item["decision"] == "NEEDS_REVIEW"
        )
        assert "CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED" in cast(
            dict[str, object], reviewed["result"]
        )["reason_codes"]

        reencoded_match = client.post(
            f"/v1/documents/{reencoded['document_id']}/matches",
            json={"purchase_order_id": purchase_order["id"]},
        )
        reencoded_match.raise_for_status()
        assert reencoded_match.json()["decision"] == "MATCHED"
        risk_response = client.get(f"/v1/matches/{reencoded_match.json()['id']}/risk")
        risk_response.raise_for_status()
        risk = risk_response.json()
        assert risk["disposition"] == "NEEDS_REVIEW"
        assert risk["review_case_id"] is not None
        assert {signal["code"] for signal in risk["signals"]} >= {
            "EXACT_BUSINESS_KEY_DUPLICATE",
            "SAME_PO_INVOICE_REPLAY",
        }

        review_po_payload = {
            "external_po_number": f"PO-REVIEW-{invoice_number}",
            "vendor_name": "Synthetic Compose Vendor",
            "currency": "USD",
            "lines": [
                {
                    "line_number": "1",
                    "description": "Industrial Filter",
                    "ordered_quantity": "2",
                    "unit_price": "500.00",
                },
                {
                    "line_number": "2",
                    "description": "Mounting Bracket",
                    "ordered_quantity": "4",
                    "unit_price": "50.00",
                },
            ],
        }
        review_po_response = client.post("/v1/purchase-orders", json=review_po_payload)
        review_po_response.raise_for_status()
        review_match = client.post(
            match_path,
            json={"purchase_order_id": review_po_response.json()["id"]},
        )
        assert review_match.status_code == 201
        assert review_match.json()["decision"] == "NEEDS_REVIEW"

        queue_response = client.get(
            "/v1/review-cases", params={"reason_code": "CURRENCY_MISMATCH"}
        )
        queue_response.raise_for_status()
        case = next(
            item
            for item in queue_response.json()["items"]
            if item["match_run_id"] == review_match.json()["id"]
        )
        headers = {"X-Reviewer-ID": "compose-reviewer"}
        claim_response = client.post(
            f"/v1/review-cases/{case['id']}/claim",
            json={"expected_version": case["version"]},
            headers=headers,
        )
        claim_response.raise_for_status()
        comment_response = client.post(
            f"/v1/review-cases/{case['id']}/comments",
            json={
                "expected_version": claim_response.json()["version"],
                "comment": "Synthetic currency mismatch verified.",
            },
            headers=headers,
        )
        comment_response.raise_for_status()
        resolve_response = client.post(
            f"/v1/review-cases/{case['id']}/resolve",
            json={
                "expected_version": comment_response.json()["version"],
                "resolution": "CORRECTION_REQUESTED",
                "reason": "Invoice currency must match the purchase order.",
            },
            headers=headers,
        )
        resolve_response.raise_for_status()
        assert resolve_response.json()["status"] == "RESOLVED"
        events_response = client.get(f"/v1/review-cases/{case['id']}/events")
        events_response.raise_for_status()
        assert [event["event_type"] for event in events_response.json()] == [
            "CASE_OPENED",
            "CASE_CLAIMED",
            "COMMENT_ADDED",
            "CASE_RESOLVED",
        ]
        audit_response = client.get(
            f"/v1/review-cases/{case['id']}/audit-verification"
        )
        audit_response.raise_for_status()
        assert audit_response.json()["valid"] is True


def test_real_stack_returns_clear_invalid_file_error() -> None:
    base_url = os.environ["API_BASE_URL"]
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post(
            "/v1/invoices",
            files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
        )
    assert response.status_code == 415
    assert "does not match declared type application/pdf" in response.json()["detail"]


def test_hybrid_fake_provider_failure_preserves_deterministic_result() -> None:
    if os.environ.get("EXPECT_EXTRACTION_STRATEGY") != "hybrid-routed":
        pytest.skip("hybrid fake-provider profile only")
    base_url = os.environ["API_BASE_URL"]
    invoice_number = f"SYN-INCOMPLETE-{uuid.uuid4()}"
    with httpx.Client(base_url=base_url, timeout=10) as client:
        upload_response = client.post(
            "/v1/invoices",
            files={
                "file": (
                    "incomplete.pdf",
                    generated_incomplete_invoice_pdf(invoice_number),
                    "application/pdf",
                )
            },
        )
        upload_response.raise_for_status()
        upload = upload_response.json()
        job = wait_for_terminal_status(client, upload["status_url"])
        assert job["status"] == "succeeded"
        response = client.get(upload["extraction_url"])
        response.raise_for_status()
        extraction = response.json()
        assert extraction["invoice"]["invoice_number"]["value"] == invoice_number
        assert extraction["hybrid"]["provider_invoked"] is True
        assert extraction["hybrid"]["provider"] == "fake"
        assert extraction["hybrid"]["provider_failure_code"] == "provider_schema_invalid"
