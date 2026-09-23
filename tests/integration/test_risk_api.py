import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.matching.service import MatchingService, PurchaseOrderService
from invoiceops.models import (
    MatchRun,
    ReviewCase,
    ReviewCaseTrigger,
    ReviewEvent,
    RiskAssessment,
    RiskSignal,
)
from invoiceops.risk.service import DuplicateRiskService
from invoiceops.schemas.matching import PurchaseOrderCreate
from invoiceops.schemas.risk import DuplicateRiskPolicy, RiskDisposition
from tests.integration.test_matching_api import (
    create_document_with_extraction,
    po_payload,
)


def create_clean_match(
    session: Session, purchase_order_id: uuid.UUID
) -> MatchRun:
    document, _ = create_document_with_extraction(session)
    return MatchingService(session).match(document.id, purchase_order_id).run


def test_different_byte_business_duplicate_opens_one_explainable_review_case(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    purchase_order = client.post("/v1/purchase-orders", json=po_payload()).json()
    po_id = uuid.UUID(purchase_order["id"])
    with db_session_factory() as session:
        first = create_clean_match(session, po_id)
        second = create_clean_match(session, po_id)
        assert first.document_id != second.document_id
        second_id = second.id

    risk_response = client.get(f"/v1/matches/{second_id}/risk")
    assert risk_response.status_code == 200
    risk = risk_response.json()
    assert risk["disposition"] == "NEEDS_REVIEW"
    assert risk["match_decision"] == "MATCHED"
    assert risk["review_status"] == "OPEN"
    assert risk["human_resolution"] is None
    assert risk["payment_authorized"] is False
    assert risk["policy_version"] == "duplicate-risk-v1"
    assert risk["policy_snapshot"]["amount_absolute_tolerance"] == "0.02"
    assert risk["policy_snapshot"]["invoice_number_similarity_threshold"] == "0.92"
    assert risk["feature_complete"] is True
    assert risk["review_case_id"] is not None
    assert risk["compared_match_run_ids"] == [str(first.id)]
    assert [signal["code"] for signal in risk["signals"]] == [
        "EXACT_BUSINESS_KEY_DUPLICATE",
        "SAME_PO_INVOICE_REPLAY",
    ]
    assert all(signal["comparison_match_run_id"] == str(first.id) for signal in risk["signals"])
    assert "score" not in risk

    direct = client.get(f"/v1/risk-assessments/{risk['id']}")
    assert direct.status_code == 200
    assert direct.json() == risk
    match = client.get(f"/v1/matches/{second_id}").json()
    assert match["decision"] == "MATCHED"
    assert match["risk_disposition"] == "NEEDS_REVIEW"
    assert match["review_status"] == "OPEN"
    assert match["human_resolution"] is None
    assert match["payment_authorized"] is False

    queue = client.get(
        "/v1/review-cases",
        params={
            "trigger_type": "RISK_SIGNAL",
            "trigger_code": "EXACT_BUSINESS_KEY_DUPLICATE",
        },
    )
    assert queue.status_code == 200
    assert [item["match_run_id"] for item in queue.json()["items"]] == [str(second_id)]
    triggers = queue.json()["items"][0]["review_triggers"]
    assert any(
        trigger["type"] == "RISK_SIGNAL"
        and trigger["source_url"] == f"/v1/risk-assessments/{risk['id']}"
        for trigger in triggers
    )
    verification = client.get(
        f"/v1/review-cases/{risk['review_case_id']}/audit-verification"
    ).json()
    assert verification["valid"] is True
    assert any(
        trigger["type"] == "RISK_SIGNAL"
        for trigger in verification["reconstructed_opening_triggers"]
    )


def test_match_review_and_duplicate_risk_share_one_case_and_opening_event(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    payload = po_payload()
    payload["currency"] = "USD"
    purchase_order = client.post("/v1/purchase-orders", json=payload).json()
    po_id = uuid.UUID(purchase_order["id"])
    with db_session_factory() as session:
        first = create_clean_match(session, po_id)
        second = create_clean_match(session, po_id)
        duplicate_retry = MatchingService(session).match(second.document_id, po_id)
        assert duplicate_retry.created is False
        assert duplicate_retry.run.id == second.id
        assert second.decision.value == "NEEDS_REVIEW"
        case = session.scalar(select(ReviewCase).where(ReviewCase.match_run_id == second.id))
        assert case is not None
        assert session.scalar(
            select(func.count()).select_from(ReviewCase).where(ReviewCase.match_run_id == second.id)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(RiskAssessment).where(
                RiskAssessment.match_run_id == second.id
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(ReviewEvent).where(
                ReviewEvent.review_case_id == case.id
            )
        ) == 1
        trigger_types = set(
            session.scalars(
                select(ReviewCaseTrigger.trigger_type).where(
                    ReviewCaseTrigger.review_case_id == case.id
                )
            )
        )
        assert trigger_types == {"MATCH_REASON", "RISK_SIGNAL"}
        opening = session.scalar(
            select(ReviewEvent).where(ReviewEvent.review_case_id == case.id)
        )
        assert opening is not None
        snapshot = opening.payload["review_triggers"]
        assert isinstance(snapshot, list)
        assert {item["type"] for item in snapshot} == {"MATCH_REASON", "RISK_SIGNAL"}
        assert first.id != second.id


def test_risk_reconciliation_is_idempotent_and_reuses_assessments(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        first = create_clean_match(session, purchase_order.id)
        second = create_clean_match(session, purchase_order.id)
        session.execute(
            ReviewCaseTrigger.__table__.delete().where(
                ReviewCaseTrigger.trigger_type == "RISK_SIGNAL"
            )
        )
        session.commit()

        first_result = DuplicateRiskService(session).reconcile()
        second_result = DuplicateRiskService(session).reconcile()
        assert first_result.inspected == second_result.inspected == 2
        assert first_result.created == second_result.created == 0
        assert first_result.reused == second_result.reused == 2
        assert first_result.failed == second_result.failed == 0
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 2
        assert session.scalar(select(func.count()).select_from(ReviewCase)) == 1
        assert session.scalar(select(func.count()).select_from(RiskSignal)) == 2
        assert first.id != second.id


def test_database_uniqueness_is_final_concurrent_assessment_safeguard(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        run = create_clean_match(session, purchase_order.id)
        stored = DuplicateRiskService(session).get_for_match(run.id)
        duplicate = RiskAssessment(
            match_run_id=run.id,
            policy_version=stored.policy_version,
            policy_snapshot=DuplicateRiskPolicy().model_dump(mode="json"),
            disposition=RiskDisposition.CLEAR,
            feature_snapshot=stored.feature_snapshot,
        )
        session.add(duplicate)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        else:
            raise AssertionError("duplicate risk assessment unexpectedly committed")
        assert session.scalar(
            select(func.count()).select_from(RiskAssessment).where(
                RiskAssessment.match_run_id == run.id
            )
        ) == 1


def test_missing_risk_resources_and_immutable_api_surface(client: TestClient) -> None:
    identifier = uuid.uuid4()
    assert client.get(f"/v1/matches/{identifier}/risk").status_code == 404
    assert client.get(f"/v1/risk-assessments/{identifier}").status_code == 404
    assert client.put(f"/v1/risk-assessments/{identifier}", json={}).status_code == 405
    assert client.delete(f"/v1/risk-assessments/{identifier}").status_code == 405


def test_missing_selected_po_vendor_routes_as_incomplete_without_false_clear(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    payload = po_payload()
    payload["vendor_name"] = None
    purchase_order = client.post("/v1/purchase-orders", json=payload).json()
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    match = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": purchase_order["id"]},
    ).json()
    assert match["decision"] == "MATCHED"
    assert match["risk_disposition"] == "NEEDS_REVIEW"
    risk = client.get(f"/v1/matches/{match['id']}/risk").json()
    assert risk["feature_complete"] is False
    assert risk["feature_snapshot"]["missing_fields"] == ["normalized_vendor"]
    assert [signal["code"] for signal in risk["signals"]] == [
        "DUPLICATE_CHECK_INCOMPLETE"
    ]
    assert risk["review_case_id"] is not None
