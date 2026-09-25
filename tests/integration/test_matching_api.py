import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.matching.service import MatchingService, PurchaseOrderService
from invoiceops.models import (
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    MatchRun,
)
from invoiceops.observability.metrics import metrics
from invoiceops.schemas.matching import MatchingPolicy, PurchaseOrderCreate
from tests.matching.helpers import invoice


def po_payload() -> dict[str, object]:
    return {
        "external_po_number": "PO-SYN-API",
        "vendor_name": "Synthetic Vendor",
        "currency": "inr",
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


def create_document_with_extraction(
    session: Session, *, status: ExtractionRunStatus = ExtractionRunStatus.SUCCEEDED
) -> tuple[Document, ExtractionRun]:
    document = Document(
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=10,
        sha256=uuid.uuid4().hex + uuid.uuid4().hex,
        object_key=f"invoices/{uuid.uuid4()}/synthetic.pdf",
    )
    session.add(document)
    session.flush()
    extraction = ExtractionRun(
        document_id=document.id,
        extractor_name="deterministic-baseline",
        extractor_version="0.2.0",
        schema_version="invoice-v1",
        status=status,
        output_json=(
            invoice().model_dump(mode="json") if status == ExtractionRunStatus.SUCCEEDED else None
        ),
    )
    session.add(extraction)
    session.commit()
    return document, extraction


def test_po_create_and_read_use_stable_decimal_strings(client: TestClient) -> None:
    created = client.post("/v1/purchase-orders", json=po_payload())

    assert created.status_code == 201
    body = created.json()
    assert body["currency"] == "INR"
    assert body["lines"][0]["ordered_quantity"] == "2.00000000"
    assert body["lines"][0]["unit_price"] == "500.00000000"
    fetched = client.get(f"/v1/purchase-orders/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_invalid_po_and_duplicate_line_numbers_return_422(client: TestClient) -> None:
    float_payload = po_payload()
    float_payload["lines"][0]["unit_price"] = 10.5  # type: ignore[index]
    assert client.post("/v1/purchase-orders", json=float_payload).status_code == 422

    duplicate_payload = po_payload()
    duplicate_payload["lines"] = [
        duplicate_payload["lines"][0],  # type: ignore[index]
        duplicate_payload["lines"][0],  # type: ignore[index]
    ]
    assert client.post("/v1/purchase-orders", json=duplicate_payload).status_code == 422


def test_match_api_is_idempotent_and_retrievable(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    with db_session_factory() as session:
        document, extraction = create_document_with_extraction(session)

    first = client.post(
        f"/v1/documents/{document.id}/matches", json={"purchase_order_id": po["id"]}
    )
    second = client.post(
        f"/v1/documents/{document.id}/matches", json={"purchase_order_id": po["id"]}
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["decision"] == "MATCHED"
    assert first.json()["matching_mode"] == "TWO_WAY"
    assert first.json()["context_fingerprint"] is None
    assert first.json()["three_way_context_url"] is None
    assert first.json()["extraction_run_id"] == str(extraction.id)
    assert first.json()["policy_snapshot"]["unit_price_relative_tolerance"] == "0.01"
    fetched = client.get(f"/v1/matches/{first.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == first.json()
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MatchRun)) == 1


def test_matching_commits_when_telemetry_recorder_raises(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    class BrokenCounter:
        def add(self, amount: int, labels: object) -> None:
            del amount, labels
            raise RuntimeError("synthetic telemetry failure")

    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    metrics.initialize()
    monkeypatch.setattr(metrics, "matching", BrokenCounter())

    response = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": po["id"]},
    )

    assert response.status_code == 201
    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MatchRun)) == 1


def test_missing_resources_and_incomplete_extraction_have_clear_statuses(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    po = client.post("/v1/purchase-orders", json=po_payload()).json()
    missing_document = client.post(
        f"/v1/documents/{uuid.uuid4()}/matches", json={"purchase_order_id": po["id"]}
    )
    assert missing_document.status_code == 404

    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session, status=ExtractionRunStatus.FAILED)
    not_ready = client.post(
        f"/v1/documents/{document.id}/matches", json={"purchase_order_id": po["id"]}
    )
    assert not_ready.status_code == 409

    missing_po = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": str(uuid.uuid4())},
    )
    assert missing_po.status_code == 404
    assert client.get(f"/v1/matches/{uuid.uuid4()}").status_code == 404


def test_recreated_service_preserves_existing_policy_snapshot(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        original_policy = MatchingPolicy(amount_absolute_tolerance=Decimal("0.02"))
        first = MatchingService(session, original_policy).match(document.id, purchase_order.id)

    with db_session_factory() as session:
        changed_defaults_same_version = MatchingPolicy(amount_absolute_tolerance=Decimal("99.00"))
        second = MatchingService(session, changed_defaults_same_version).match(
            document.id, purchase_order.id
        )

        assert second.created is False
        assert second.run.id == first.run.id
        assert second.run.policy_snapshot["amount_absolute_tolerance"] == "0.02"


def test_database_constraint_rejects_duplicate_match_tuple(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        document, extraction = create_document_with_extraction(session)
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        result = MatchingService(session).match(document.id, purchase_order.id).run
        session.expunge(result)
        duplicate = MatchRun(
            document_id=document.id,
            purchase_order_id=purchase_order.id,
            extraction_run_id=extraction.id,
            policy_version=result.policy_version,
            policy_snapshot=result.policy_snapshot,
            decision=result.decision,
            result_json=result.result_json,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_hybrid_becomes_current_without_rewriting_historical_match(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        document, baseline = create_document_with_extraction(session)
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        historical = MatchingService(session).match(document.id, purchase_order.id).run
        historical_id = historical.id
        assert historical.extraction_run_id == baseline.id

        hybrid = ExtractionRun(
            document_id=document.id,
            extractor_name="hybrid-routed",
            extractor_version="0.3.0",
            schema_version="invoice-v1",
            status=ExtractionRunStatus.SUCCEEDED,
            output_json=invoice().model_dump(mode="json"),
        )
        session.add(hybrid)
        session.commit()
        current = MatchingService(session).match(document.id, purchase_order.id)

        assert current.created is True
        assert current.run.extraction_run_id == hybrid.id
        assert current.run.id != historical_id
        preserved = session.get(MatchRun, historical_id)
        assert preserved is not None and preserved.extraction_run_id == baseline.id
