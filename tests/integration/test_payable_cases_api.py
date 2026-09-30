import io

import fitz
from fastapi.testclient import TestClient


def pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    body = document.tobytes()
    document.close()
    return body


def test_case_creation_and_attachment_retries_are_idempotent(client: TestClient) -> None:
    created = client.post("/v1/cases", json={"idempotency_key": "case-1"})
    assert created.status_code == 201
    case = created.json()
    replay = client.post("/v1/cases", json={"idempotency_key": "case-1"})
    assert replay.status_code == 201
    assert replay.json()["id"] == case["id"]

    body = pdf_bytes("Invoice Number INV-100")
    form = {
        "role": "INVOICE",
        "idempotency_key": "attach-invoice-1",
        "expected_case_version": str(case["version"]),
    }
    first = client.post(
        f"/v1/cases/{case['id']}/documents",
        data=form,
        files={"file": ("invoice.pdf", io.BytesIO(body), "application/pdf")},
    )
    assert first.status_code == 202, first.text
    repeated = client.post(
        f"/v1/cases/{case['id']}/documents",
        data=form,
        files={"file": ("invoice.pdf", io.BytesIO(body), "application/pdf")},
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["replayed"] is True
    assert repeated.json()["attachment"]["id"] == first.json()["attachment"]["id"]

    changed_payload = client.post(
        f"/v1/cases/{case['id']}/documents",
        data=form,
        files={
            "file": (
                "different.pdf",
                io.BytesIO(pdf_bytes("Invoice Number INV-OTHER")),
                "application/pdf",
            )
        },
    )
    assert changed_payload.status_code == 409
    assert changed_payload.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"

    stale = client.post(
        f"/v1/cases/{case['id']}/documents",
        data={
            "role": "GOODS_RECEIPT",
            "idempotency_key": "stale-receipt",
            "expected_case_version": str(case["version"]),
        },
        files={
            "file": (
                "receipt.pdf",
                io.BytesIO(pdf_bytes("Goods Receipt GR-STALE")),
                "application/pdf",
            )
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "STALE_CASE_VERSION"


def test_supporting_files_are_real_attachments_and_partial_failure_is_isolated(
    client: TestClient,
) -> None:
    case = client.post("/v1/cases", json={"idempotency_key": "case-2"}).json()
    invoice = client.post(
        f"/v1/cases/{case['id']}/documents",
        data={
            "role": "INVOICE",
            "idempotency_key": "invoice-2",
            "expected_case_version": str(case["version"]),
        },
        files={
            "file": (
                "invoice.pdf",
                io.BytesIO(pdf_bytes("Invoice Number INV-200")),
                "application/pdf",
            )
        },
    ).json()
    purchase_order = client.post(
        f"/v1/cases/{case['id']}/documents",
        data={
            "role": "PURCHASE_ORDER",
            "idempotency_key": "po-2",
            "expected_case_version": str(invoice["case"]["version"]),
        },
        files={
            "file": (
                "po.pdf",
                io.BytesIO(pdf_bytes("Purchase Order PO-200")),
                "application/pdf",
            )
        },
    )
    assert purchase_order.status_code == 202, purchase_order.text

    invalid_receipt = client.post(
        f"/v1/cases/{case['id']}/documents",
        data={
            "role": "GOODS_RECEIPT",
            "idempotency_key": "bad-receipt-2",
            "expected_case_version": str(purchase_order.json()["case"]["version"]),
        },
        files={"file": ("receipt.pdf", io.BytesIO(b"not a pdf"), "application/pdf")},
    )
    assert invalid_receipt.status_code == 415
    documents = client.get(f"/v1/cases/{case['id']}/documents")
    assert documents.status_code == 200
    assert [item["role"] for item in documents.json()] == ["INVOICE", "PURCHASE_ORDER"]


def test_receipt_replacement_is_append_only_and_only_successor_is_active(
    client: TestClient,
) -> None:
    payable_case = client.post(
        "/v1/cases", json={"idempotency_key": "receipt-replacement-case"}
    ).json()
    first = client.post(
        f"/v1/cases/{payable_case['id']}/documents",
        data={
            "role": "GOODS_RECEIPT",
            "idempotency_key": "receipt-original",
            "expected_case_version": str(payable_case["version"]),
        },
        files={
            "file": (
                "receipt-original.pdf",
                io.BytesIO(pdf_bytes("Goods Receipt GR-OLD")),
                "application/pdf",
            )
        },
    )
    assert first.status_code == 202, first.text
    first_body = first.json()

    replacement = client.post(
        f"/v1/cases/{payable_case['id']}/documents",
        data={
            "role": "GOODS_RECEIPT",
            "idempotency_key": "receipt-replacement",
            "expected_case_version": str(first_body["case"]["version"]),
            "supersedes_id": first_body["attachment"]["id"],
        },
        files={
            "file": (
                "receipt-replacement.pdf",
                io.BytesIO(pdf_bytes("Goods Receipt GR-NEW")),
                "application/pdf",
            )
        },
    )
    assert replacement.status_code == 202, replacement.text

    documents = client.get(f"/v1/cases/{payable_case['id']}/documents").json()
    assert len(documents) == 2
    assert documents[0]["is_active"] is False
    assert documents[1]["is_active"] is True
    assert documents[1]["supersedes_id"] == documents[0]["id"]
