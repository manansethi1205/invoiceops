import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.models import MatchRun, ThreeWayAllocation
from tests.integration.test_matching_api import (
    create_document_with_extraction,
    po_payload,
)
from tests.matching.helpers import invoice, invoice_line


def _receipt_payload(po: dict[str, object], *, number: str = "GRN-SYN-1") -> dict[str, object]:
    lines = po["lines"]
    assert isinstance(lines, list)
    return {
        "purchase_order_id": po["id"],
        "external_receipt_number": number,
        "received_at": datetime(2026, 9, 20, 12, tzinfo=UTC).isoformat(),
        "lines": [
            {
                "purchase_order_line_id": lines[0]["id"],
                "accepted_quantity": "2",
            },
            {
                "purchase_order_line_id": lines[1]["id"],
                "accepted_quantity": "4",
            },
        ],
    }


def test_receipt_replay_is_idempotent_and_conflicting_payload_is_rejected(
    client: TestClient,
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    payload = _receipt_payload(po)
    first = client.post("/v1/goods-receipts", json=payload)
    replay = client.post("/v1/goods-receipts", json=payload)
    changed = dict(payload)
    changed["lines"] = [dict(payload["lines"][0], accepted_quantity="1")]  # type: ignore[index]
    conflict = client.post("/v1/goods-receipts", json=changed)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "CONFLICTING_RECEIPT_REPLAY"
    assert client.get(f"/v1/goods-receipts/{first.json()['id']}").json() == first.json()
    listed = client.get(f"/v1/purchase-orders/{po['id']}/goods-receipts")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [first.json()["id"]]


def test_three_way_match_persists_context_and_allocates_once(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    receipt = client.post("/v1/goods-receipts", json=_receipt_payload(po))
    assert receipt.status_code == 201
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)

    first = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    )
    replay = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    )

    assert first.status_code == 201
    body = first.json()
    assert body["matching_mode"] == "THREE_WAY"
    assert body["decision"] == "MATCHED"
    assert body["policy_version"] == "three-way-v1"
    assert body["context_fingerprint"]
    assert replay.status_code == 200
    assert replay.json()["id"] == body["id"]
    context = client.get(body["three_way_context_url"])
    assert context.status_code == 200
    assert context.json()["context_fingerprint"] == body["context_fingerprint"]
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MatchRun)) == 1
        assert session.scalar(select(func.count()).select_from(ThreeWayAllocation)) == 2


def test_missing_receipt_routes_to_review_without_allocation(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    response = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["decision"] == "NEEDS_REVIEW"
    assert "NO_GOODS_RECEIPT" in body["result"]["reason_codes"]
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ThreeWayAllocation)) == 0


def test_reversal_changes_context_and_is_not_repeatable(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    receipt = client.post("/v1/goods-receipts", json=_receipt_payload(po)).json()
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    first = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    ).json()
    reversal = client.post(
        f"/v1/goods-receipts/{receipt['id']}/reverse",
        headers={"X-Actor-ID": "synthetic-receiver"},
        json={"reason": "Synthetic receiving correction"},
    )
    repeated = client.post(
        f"/v1/goods-receipts/{receipt['id']}/reverse",
        headers={"X-Actor-ID": "synthetic-receiver"},
        json={"reason": "Repeated request"},
    )
    second = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    ).json()

    assert reversal.status_code == 200
    assert repeated.status_code == 409
    assert second["id"] != first["id"]
    assert second["context_fingerprint"] != first["context_fingerprint"]
    assert second["decision"] == "NEEDS_REVIEW"
    assert "GOODS_RECEIPT_REVERSED" in second["result"]["reason_codes"]
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ThreeWayAllocation)) == 2


def test_later_receipt_creates_new_immutable_context(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    client.post("/v1/goods-receipts", json=_receipt_payload(po))
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    first = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    ).json()
    later = _receipt_payload(po, number="GRN-SYN-2")
    later["received_at"] = datetime(2026, 9, 21, 10, tzinfo=UTC).isoformat()
    assert client.post("/v1/goods-receipts", json=later).status_code == 201
    second = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    ).json()
    assert second["id"] != first["id"]
    assert second["context_fingerprint"] != first["context_fingerprint"]
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ThreeWayAllocation)) == 2


def test_later_receipt_does_not_allocate_the_same_invoice_twice(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    payload = po_payload()
    payload["lines"] = [
        {
            "line_number": "1",
            "description": "Industrial Filter",
            "ordered_quantity": "10",
            "unit_price": "500.00",
        }
    ]
    po = client.post("/v1/purchase-orders", json=payload).json()

    def receive(number: str, quantity: str) -> None:
        response = client.post(
            "/v1/goods-receipts",
            json={
                "purchase_order_id": po["id"],
                "external_receipt_number": number,
                "received_at": datetime(2026, 9, 20, 12, tzinfo=UTC).isoformat(),
                "lines": [
                    {
                        "purchase_order_line_id": po["lines"][0]["id"],
                        "accepted_quantity": quantity,
                    }
                ],
            },
        )
        assert response.status_code == 201

    receive("GRN-FIRST", "4")
    with db_session_factory() as session:
        document, extraction = create_document_with_extraction(session)
        extraction.output_json = invoice(
            subtotal="2000",
            tax="0",
            total="2000",
            lines=[invoice_line("Industrial Filter", "4", "500", "2000")],
        ).model_dump(mode="json")
        session.commit()

    first = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    )
    assert first.status_code == 201
    assert first.json()["decision"] == "MATCHED"

    receive("GRN-LATER", "4")
    reevaluated = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
    )
    assert reevaluated.status_code == 201
    assert reevaluated.json()["id"] != first.json()["id"]
    assert reevaluated.json()["decision"] == "MATCHED"
    with db_session_factory() as session:
        allocations = list(session.scalars(select(ThreeWayAllocation)))
        assert len(allocations) == 1
        assert allocations[0].document_id == document.id
        assert allocations[0].allocated_quantity == Decimal("4")


def test_receipt_mutations_use_the_shared_purchase_order_lock(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from invoiceops import po_locking
    from invoiceops.receipts import service as receipts_service

    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    calls: list[str] = []

    def recording_lock(
        session: Session, purchase_order_id: uuid.UUID, *, include_lines: bool = False
    ) -> object:
        calls.append(str(purchase_order_id))
        return po_locking.lock_purchase_order(
            session, purchase_order_id, include_lines=include_lines
        )

    monkeypatch.setattr(receipts_service, "lock_purchase_order", recording_lock)
    receipt = client.post("/v1/goods-receipts", json=_receipt_payload(po))
    assert receipt.status_code == 201
    reversal = client.post(
        f"/v1/goods-receipts/{receipt.json()['id']}/reverse",
        headers={"X-Actor-ID": "synthetic-receiver"},
        json={"reason": "Synthetic receiving correction"},
    )
    assert reversal.status_code == 200
    assert calls == [po["id"], po["id"]]


def test_receipt_requires_unverified_development_actor_for_reversal(
    client: TestClient,
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    receipt = client.post("/v1/goods-receipts", json=_receipt_payload(po)).json()
    response = client.post(
        f"/v1/goods-receipts/{receipt['id']}/reverse",
        json={"reason": "Synthetic correction"},
    )
    assert response.status_code == 422


def test_partial_invoices_consume_remaining_receipt_quantity(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    payload = po_payload()
    payload["lines"] = [
        {
            "line_number": "1",
            "description": "Industrial Filter",
            "ordered_quantity": "10",
            "unit_price": "500.00",
        }
    ]
    po = client.post("/v1/purchase-orders", json=payload).json()
    receipt_payload = {
        "purchase_order_id": po["id"],
        "external_receipt_number": "GRN-PARTIAL",
        "received_at": datetime(2026, 9, 20, 12, tzinfo=UTC).isoformat(),
        "lines": [
            {
                "purchase_order_line_id": po["lines"][0]["id"],
                "accepted_quantity": "10",
            }
        ],
    }
    assert client.post("/v1/goods-receipts", json=receipt_payload).status_code == 201
    document_ids = []
    with db_session_factory() as session:
        for quantity in ("4", "6", "1"):
            document, extraction = create_document_with_extraction(session)
            amount = str(Decimal(quantity) * Decimal("500"))
            extraction.output_json = invoice(
                subtotal=amount,
                tax="0",
                total=amount,
                lines=[invoice_line("Industrial Filter", quantity, "500", amount)],
            ).model_dump(mode="json")
            document_ids.append(document.id)
        session.commit()

    responses = [
        client.post(
            f"/v1/documents/{document_id}/matches",
            json={"purchase_order_id": po["id"], "mode": "THREE_WAY"},
        ).json()
        for document_id in document_ids
    ]
    assert [item["decision"] for item in responses] == [
        "MATCHED",
        "MATCHED",
        "NEEDS_REVIEW",
    ]
    assert "CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED" in responses[2]["result"]["reason_codes"]
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ThreeWayAllocation)) == 2
