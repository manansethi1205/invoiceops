import uuid
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from invoiceops.matching.service import MatchingService, PurchaseOrderService
from invoiceops.models import (
    MatchRun,
    ReviewCase,
    ReviewCaseTrigger,
    ReviewEvent,
    RiskAssessment,
)
from invoiceops.observability.metrics import metrics
from invoiceops.review.audit import AUDIT_HASH_V1, event_hash
from invoiceops.review.service import MATCH_REASON_TRIGGER, ReviewService
from invoiceops.review.state import ReviewTransitionError
from invoiceops.schemas.matching import PurchaseOrderCreate
from tests.integration.test_matching_api import (
    create_document_with_extraction,
    po_payload,
)


def review_po_payload() -> dict[str, object]:
    payload = po_payload()
    payload["currency"] = "USD"
    return payload


def create_review_case(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> dict[str, object]:
    purchase_order = client.post("/v1/purchase-orders", json=review_po_payload()).json()
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
    response = client.post(
        f"/v1/documents/{document.id}/matches",
        json={"purchase_order_id": purchase_order["id"]},
    )
    assert response.status_code == 201
    assert response.json()["decision"] == "NEEDS_REVIEW"
    queue = client.get("/v1/review-cases").json()
    return next(
        item for item in queue["items"] if item["match_run_id"] == response.json()["id"]
    )


def test_needs_review_match_atomically_opens_one_case_and_event(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    assert case["status"] == "OPEN"
    assert case["version"] == 1
    assert "CURRENCY_MISMATCH" in case["reason_codes"]

    # Repeating matching is idempotent and does not append another opening event.
    with db_session_factory() as session:
        stored_case = session.get(ReviewCase, uuid.UUID(str(case["id"])))
        assert stored_case is not None
        run = session.get(MatchRun, stored_case.match_run_id)
        assert run is not None
        duplicate = MatchingService(session).match(run.document_id, run.purchase_order_id)
        assert duplicate.created is False
        assert session.scalar(select(func.count()).select_from(ReviewCase)) == 1
        assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 1
        assert session.scalar(select(func.count()).select_from(ReviewCaseTrigger)) >= 1


def test_matched_run_does_not_create_review_case(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(po_payload())
        )
        run = MatchingService(session).match(document.id, purchase_order.id).run
        assert run.decision.value == "MATCHED"
        assert session.scalar(select(func.count()).select_from(ReviewCase)) == 0


def test_claim_comment_release_reclaim_and_resolve_with_auditable_history(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = case["id"]
    reviewer = {"X-Reviewer-ID": "reviewer-a"}

    claimed = client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 1},
        headers=reviewer,
    )
    assert claimed.status_code == 200
    assert claimed.json()["version"] == 2

    commented = client.post(
        f"/v1/review-cases/{case_id}/comments",
        json={"expected_version": 2, "comment": "PO currency differs; checking contract."},
        headers={"X-Reviewer-ID": "reviewer-b"},
    )
    assert commented.status_code == 200
    assert commented.json()["assigned_reviewer_id"] == "reviewer-a"

    released = client.post(
        f"/v1/review-cases/{case_id}/release",
        json={"expected_version": 3, "reason": "Handing over to day shift"},
        headers=reviewer,
    )
    assert released.status_code == 200
    assert released.json()["status"] == "OPEN"

    reclaimed = client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 4},
        headers={"X-Reviewer-ID": "reviewer-c"},
    )
    assert reclaimed.status_code == 200

    resolved = client.post(
        f"/v1/review-cases/{case_id}/resolve",
        json={
            "expected_version": 5,
            "resolution": "CORRECTION_REQUESTED",
            "reason": "Vendor must issue an INR invoice matching the PO.",
        },
        headers={"X-Reviewer-ID": "reviewer-c"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    assert resolved.json()["version"] == 6

    events = client.get(f"/v1/review-cases/{case_id}/events")
    event_items = events.json()
    assert [event["event_type"] for event in event_items] == [
        "CASE_OPENED",
        "CASE_CLAIMED",
        "COMMENT_ADDED",
        "CASE_RELEASED",
        "CASE_CLAIMED",
        "CASE_RESOLVED",
    ]
    assert event_items[0]["previous_hash"] is None
    assert {event["hash_version"] for event in event_items} == {"review-audit-v2"}
    for previous, current in zip(event_items, event_items[1:], strict=False):
        assert current["previous_hash"] == previous["event_hash"]
        assert len(current["event_hash"]) == 64
    verification = client.get(f"/v1/review-cases/{case_id}/audit-verification")
    assert verification.json()["valid"] is True
    assert verification.json()["reconstructed_status"] == "RESOLVED"

    detail = client.get(f"/v1/review-cases/{case_id}").json()
    failed_checks = [
        check for check in detail["match"]["result"]["checks"] if check["status"] == "failed"
    ]
    assert failed_checks
    assert any(check["evidence"] for check in failed_checks)
    assert detail["extraction_version"] == "0.2.0"
    assert detail["events_url"].endswith(f"/v1/review-cases/{case_id}/events")
    assert client.delete(f"/v1/review-cases/{case_id}/events").status_code == 405
    assert client.put(f"/v1/review-cases/{case_id}/events", json=[]).status_code == 405


def test_review_transition_commits_when_telemetry_recorder_raises(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    class BrokenCounter:
        def add(self, amount: int, labels: object) -> None:
            del amount, labels
            raise RuntimeError("synthetic telemetry failure")

    case = create_review_case(client, db_session_factory)
    metrics.initialize()
    monkeypatch.setattr(metrics, "review", BrokenCounter())

    response = client.post(
        f"/v1/review-cases/{case['id']}/claim",
        json={"expected_version": 1},
        headers={"X-Reviewer-ID": "reviewer-telemetry-test"},
    )

    assert response.status_code == 200
    with db_session_factory() as session:
        stored = session.get(ReviewCase, uuid.UUID(str(case["id"])))
        assert stored is not None
        assert stored.status.value == "CLAIMED"
        assert stored.version == 2


def test_concurrency_ownership_identity_and_terminal_guards(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = case["id"]
    missing_identity = client.post(
        f"/v1/review-cases/{case_id}/claim", json={"expected_version": 1}
    )
    assert missing_identity.status_code == 422
    assert missing_identity.json()["detail"]["code"] == "INVALID_REVIEWER_ID"

    assert client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 1},
        headers={"X-Reviewer-ID": "reviewer-a"},
    ).status_code == 200

    stale = client.post(
        f"/v1/review-cases/{case_id}/comments",
        json={"expected_version": 1, "comment": "stale"},
        headers={"X-Reviewer-ID": "reviewer-a"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "STALE_VERSION"

    unauthorized = client.post(
        f"/v1/review-cases/{case_id}/resolve",
        json={
            "expected_version": 2,
            "resolution": "REJECTED_DOCUMENT",
            "reason": "Not valid",
        },
        headers={"X-Reviewer-ID": "reviewer-b"},
    )
    assert unauthorized.status_code == 409
    assert unauthorized.json()["detail"]["code"] == "REVIEWER_OWNERSHIP_CONFLICT"

    blank = client.post(
        f"/v1/review-cases/{case_id}/resolve",
        json={"expected_version": 2, "resolution": "REJECTED_DOCUMENT", "reason": "  "},
        headers={"X-Reviewer-ID": "reviewer-a"},
    )
    assert blank.status_code == 422

    before_resolution = deepcopy(client.get(f"/v1/review-cases/{case_id}").json()["match"])
    resolved = client.post(
        f"/v1/review-cases/{case_id}/resolve",
        json={
            "expected_version": 2,
            "resolution": "ACCEPTED_EXCEPTION",
            "reason": "Supervisor documented the contractual exception.",
        },
        headers={"X-Reviewer-ID": "reviewer-a"},
    )
    assert resolved.status_code == 200
    after_resolution = client.get(f"/v1/review-cases/{case_id}").json()["match"]
    assert before_resolution.pop("review_status") == "CLAIMED"
    assert before_resolution.pop("human_resolution") is None
    assert after_resolution.pop("review_status") == "RESOLVED"
    assert after_resolution.pop("human_resolution") == "ACCEPTED_EXCEPTION"
    assert after_resolution == before_resolution
    assert after_resolution["decision"] == "NEEDS_REVIEW"
    assert "payment" not in resolved.json()
    reopen = client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 3},
        headers={"X-Reviewer-ID": "reviewer-a"},
    )
    assert reopen.status_code == 409
    assert reopen.json()["detail"]["code"] == "INVALID_TRANSITION"

    with db_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 3


def test_two_loaded_claims_have_one_compare_and_swap_winner(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = uuid.UUID(str(case["id"]))
    with db_session_factory() as first_session, db_session_factory() as second_session:
        first_service = ReviewService(first_session)
        second_service = ReviewService(second_session)
        assert first_service.get(case_id).version == 1
        assert second_service.get(case_id).version == 1

        winner = first_service.claim(case_id, "reviewer-a", 1)
        assert winner.assigned_reviewer_id == "reviewer-a"
        with pytest.raises(ReviewTransitionError) as raised:
            second_service.claim(case_id, "reviewer-b", 1)
        assert raised.value.code == "STALE_VERSION"

    with db_session_factory() as session:
        stored = ReviewService(session).get(case_id)
        assert stored.assigned_reviewer_id == "reviewer-a"
        assert session.scalar(select(func.count()).select_from(ReviewEvent)) == 2


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("sequence", "SEQUENCE_GAP_AT_2"),
        ("previous_hash", "PREVIOUS_HASH_MISMATCH_AT_2"),
        ("state", "MATERIALIZED_STATE_MISMATCH"),
    ],
)
def test_audit_verification_detects_structural_and_state_corruption(
    corruption: str,
    expected_error: str,
    client: TestClient,
    db_session_factory: sessionmaker[Session],
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = uuid.UUID(str(case["id"]))
    claim_response = client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 1},
        headers={"X-Reviewer-ID": "reviewer-a"},
    )
    assert claim_response.status_code == 200

    with db_session_factory() as session:
        if corruption == "state":
            stored_case = session.get(ReviewCase, case_id)
            assert stored_case is not None
            stored_case.version = 9
        else:
            event = session.scalar(
                select(ReviewEvent).where(
                    ReviewEvent.review_case_id == case_id,
                    ReviewEvent.sequence_number == 2,
                )
            )
            assert event is not None
            if corruption == "sequence":
                event.sequence_number = 3
            else:
                event.previous_hash = "0" * 64
        session.commit()

    verification = client.get(f"/v1/review-cases/{case_id}/audit-verification").json()
    assert verification["valid"] is False
    assert expected_error in verification["errors"]


def test_queue_filters_cursor_reconciliation_and_tamper_detection(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    other_case = create_review_case(client, db_session_factory)
    case_id = uuid.UUID(str(case["id"]))
    filtered = client.get("/v1/review-cases?status=OPEN&reason_code=CURRENCY_MISMATCH&limit=1")
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["next_cursor"] is not None
    next_page = client.get(
        "/v1/review-cases",
        params={"cursor": filtered.json()["next_cursor"], "limit": 1},
    )
    assert next_page.status_code == 200
    assert next_page.json()["items"][0]["id"] != filtered.json()["items"][0]["id"]
    assert client.get("/v1/review-cases?cursor=not-a-cursor").status_code == 400

    claim_response = client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 1},
        headers={"X-Reviewer-ID": "queue-owner"},
    )
    assert claim_response.status_code == 200
    assigned = client.get(
        "/v1/review-cases",
        params={"assignee": "queue-owner", "created_after": "2020-01-01T00:00:00Z"},
    ).json()
    assert [item["id"] for item in assigned["items"]] == [str(case_id)]

    with db_session_factory() as session:
        missing_case = session.get(ReviewCase, uuid.UUID(str(other_case["id"])))
        assert missing_case is not None
        session.delete(missing_case)
        session.commit()
        first = ReviewService(session).reconcile()
        second = ReviewService(session).reconcile()
        assert (first.created, second.created) == (1, 0)
        assert first.inspected == 2
        event = session.scalar(
            select(ReviewEvent).where(
                ReviewEvent.review_case_id == case_id, ReviewEvent.sequence_number == 1
            )
        )
        assert event is not None
        event.payload = {"tampered": True}
        session.commit()

    verification = client.get(f"/v1/review-cases/{case_id}/audit-verification").json()
    assert verification["valid"] is False
    assert "EVENT_HASH_MISMATCH_AT_1" in verification["errors"]


def test_legacy_v1_event_hash_still_verifies(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = uuid.UUID(str(case["id"]))
    with db_session_factory() as session:
        event = session.scalar(
            select(ReviewEvent).where(ReviewEvent.review_case_id == case_id)
        )
        assert event is not None
        event.hash_version = AUDIT_HASH_V1
        event.event_hash = event_hash(
            case_id=case_id,
            sequence_number=event.sequence_number,
            event_type=event.event_type,
            actor_id=event.actor_id,
            occurred_at=event.occurred_at,
            payload=event.payload,
            previous_hash=event.previous_hash,
            hash_version=AUDIT_HASH_V1,
        )
        session.commit()

    verification = client.get(f"/v1/review-cases/{case_id}/audit-verification").json()
    assert verification["valid"] is True


def test_mixed_v1_v2_event_chain_remains_verifiable(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    case_id = uuid.UUID(str(case["id"]))
    assert client.post(
        f"/v1/review-cases/{case_id}/claim",
        json={"expected_version": 1},
        headers={"X-Reviewer-ID": "reviewer-a"},
    ).status_code == 200
    with db_session_factory() as session:
        events = list(
            session.scalars(
                select(ReviewEvent)
                .where(ReviewEvent.review_case_id == case_id)
                .order_by(ReviewEvent.sequence_number)
            )
        )
        first, second = events
        first.hash_version = AUDIT_HASH_V1
        first.event_hash = event_hash(
            case_id=case_id,
            sequence_number=first.sequence_number,
            event_type=first.event_type,
            actor_id=first.actor_id,
            occurred_at=first.occurred_at,
            payload=first.payload,
            previous_hash=None,
            hash_version=AUDIT_HASH_V1,
        )
        second.previous_hash = first.event_hash
        second.event_hash = event_hash(
            case_id=case_id,
            sequence_number=second.sequence_number,
            event_type=second.event_type,
            actor_id=second.actor_id,
            occurred_at=second.occurred_at,
            payload=second.payload,
            previous_hash=second.previous_hash,
            hash_version=second.hash_version,
        )
        session.commit()

    verification = client.get(f"/v1/review-cases/{case_id}/audit-verification").json()
    assert verification["valid"] is True
    assert verification["event_count"] == 2


def test_match_reason_filter_uses_normalized_trigger_rows(
    client: TestClient, db_session_factory: sessionmaker[Session]
) -> None:
    case = create_review_case(client, db_session_factory)
    with db_session_factory() as session:
        triggers = list(
            session.scalars(
                select(ReviewCaseTrigger).where(
                    ReviewCaseTrigger.review_case_id == uuid.UUID(str(case["id"])),
                    ReviewCaseTrigger.trigger_type == MATCH_REASON_TRIGGER,
                )
            )
        )
        assert {trigger.trigger_code for trigger in triggers} >= {"CURRENCY_MISMATCH"}

    matching = client.get(
        "/v1/review-cases", params={"reason_code": "CURRENCY_MISMATCH"}
    ).json()
    nonmatching = client.get(
        "/v1/review-cases", params={"reason_code": "NEGATIVE_AMOUNT"}
    ).json()
    assert [item["id"] for item in matching["items"]] == [str(case["id"])]
    assert nonmatching["items"] == []


def test_match_and_review_opening_roll_back_together(
    monkeypatch: pytest.MonkeyPatch, db_session_factory: sessionmaker[Session]
) -> None:
    with db_session_factory() as session:
        document, _ = create_document_with_extraction(session)
        purchase_order = PurchaseOrderService(session).create(
            PurchaseOrderCreate.model_validate(review_po_payload())
        )

        def fail_opening(
            _session: Session, _run: MatchRun, _risk: object
        ) -> tuple[None, bool]:
            raise RuntimeError("synthetic opening failure")

        monkeypatch.setattr("invoiceops.matching.service.ensure_review_case", fail_opening)
        with pytest.raises(RuntimeError, match="synthetic opening failure"):
            MatchingService(session).match(document.id, purchase_order.id)
        session.rollback()
        assert session.scalar(select(func.count()).select_from(MatchRun)) == 0
        assert session.scalar(select(func.count()).select_from(RiskAssessment)) == 0
        assert session.scalar(select(func.count()).select_from(ReviewCase)) == 0
