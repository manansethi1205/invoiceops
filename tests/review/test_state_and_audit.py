import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from invoiceops.review.audit import AUDIT_HASH_V1, AUDIT_HASH_V2, canonical_json, event_hash
from invoiceops.review.state import (
    ReviewState,
    ReviewTransitionError,
    claim,
    comment,
    release,
    resolve,
)
from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus


def open_state(version: int = 1) -> ReviewState:
    return ReviewState(ReviewStatus.OPEN, None, version)


def claimed_state(version: int = 2, assignee: str = "reviewer-a") -> ReviewState:
    return ReviewState(ReviewStatus.CLAIMED, assignee, version)


def test_allowed_state_transitions_preserve_explicit_values() -> None:
    claimed = claim(open_state(), "reviewer-a", 1)
    assert (claimed.status, claimed.assignee) == (ReviewStatus.CLAIMED, "reviewer-a")

    noted = comment(claimed_state(), "reviewer-b", 2, "Independent observation")
    assert noted.status == ReviewStatus.CLAIMED
    assert noted.assignee == "reviewer-a"

    released = release(claimed_state(), "reviewer-a", 2, "Shift ended")
    assert (released.status, released.assignee) == (ReviewStatus.OPEN, None)

    resolved = resolve(
        claimed_state(),
        "reviewer-a",
        2,
        ReviewResolution.CORRECTION_REQUESTED,
        "Quantity differs from the purchase order",
    )
    assert resolved.status == ReviewStatus.RESOLVED
    assert resolved.resolution == ReviewResolution.CORRECTION_REQUESTED


@pytest.mark.parametrize(
    ("operation", "code"),
    [
        (lambda: claim(claimed_state(), "reviewer-a", 2), "INVALID_TRANSITION"),
        (lambda: release(open_state(), "reviewer-a", 1, "no"), "INVALID_TRANSITION"),
        (
            lambda: resolve(
                open_state(),
                "reviewer-a",
                1,
                ReviewResolution.REJECTED_DOCUMENT,
                "invalid direct resolution",
            ),
            "INVALID_TRANSITION",
        ),
        (
            lambda: release(claimed_state(), "reviewer-b", 2, "no"),
            "REVIEWER_OWNERSHIP_CONFLICT",
        ),
        (
            lambda: resolve(
                claimed_state(),
                "reviewer-b",
                2,
                ReviewResolution.REJECTED_DOCUMENT,
                "Invalid",
            ),
            "REVIEWER_OWNERSHIP_CONFLICT",
        ),
        (lambda: comment(open_state(), "reviewer-a", 9, "note"), "STALE_VERSION"),
        (
            lambda: resolve(
                claimed_state(),
                "reviewer-a",
                2,
                ReviewResolution.REJECTED_DOCUMENT,
                " ",
            ),
            "RESOLUTION_REASON_REQUIRED",
        ),
        (
            lambda: comment(
                ReviewState(
                    ReviewStatus.RESOLVED,
                    "reviewer-a",
                    3,
                    ReviewResolution.ACCEPTED_EXCEPTION,
                    "Approved deviation",
                ),
                "reviewer-a",
                3,
                "late note",
            ),
            "CASE_RESOLVED",
        ),
    ],
)
def test_invalid_transitions_have_stable_codes(operation: object, code: str) -> None:
    with pytest.raises(ReviewTransitionError) as raised:
        operation()  # type: ignore[operator]
    assert raised.value.code == code


def test_canonical_hash_is_key_order_independent_and_decimal_safe() -> None:
    case_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
    occurred_at = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
    left = {"amount": Decimal("10.20"), "note": "synthetic"}
    right = {"note": "synthetic", "amount": Decimal("10.20")}

    assert canonical_json(left) == canonical_json(right)
    assert event_hash(
        case_id=case_id,
        sequence_number=1,
        event_type=ReviewEventType.CASE_OPENED,
        actor_id="system:matching",
        occurred_at=occurred_at,
        payload=left,
        previous_hash=None,
    ) == event_hash(
        case_id=case_id,
        sequence_number=1,
        event_type=ReviewEventType.CASE_OPENED,
        actor_id="system:matching",
        occurred_at=occurred_at,
        payload=right,
        previous_hash=None,
    )


def test_v2_hash_uses_a_versioned_structured_envelope_and_v1_remains_stable() -> None:
    case_id = uuid.UUID("22222222-2222-2222-2222-222222222222")
    occurred_at = datetime(2026, 9, 24, 8, 30, tzinfo=UTC)
    parameters = {
        "case_id": case_id,
        "sequence_number": 2,
        "event_type": ReviewEventType.CASE_CLAIMED,
        "actor_id": "reviewer-a",
        "occurred_at": occurred_at,
        "payload": {"reviewer_id": "reviewer-a"},
        "previous_hash": "a" * 64,
    }

    v1 = event_hash(**parameters, hash_version=AUDIT_HASH_V1)  # type: ignore[arg-type]
    v2 = event_hash(**parameters, hash_version=AUDIT_HASH_V2)  # type: ignore[arg-type]

    assert len(v1) == len(v2) == 64
    assert v1 != v2
    assert v2 == event_hash(**parameters)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("case_id", uuid.UUID("55555555-5555-5555-5555-555555555555")),
        ("sequence_number", 3),
        ("event_type", ReviewEventType.COMMENT_ADDED),
        ("actor_id", "reviewer-b"),
        ("occurred_at", datetime(2026, 9, 24, 8, 31, tzinfo=UTC)),
        ("payload", {"reviewer_id": "reviewer-b"}),
        ("previous_hash", "b" * 64),
    ],
)
def test_v2_hash_changes_when_any_envelope_field_changes(
    field: str, changed: object
) -> None:
    parameters: dict[str, object] = {
        "case_id": uuid.UUID("33333333-3333-3333-3333-333333333333"),
        "sequence_number": 2,
        "event_type": ReviewEventType.CASE_CLAIMED,
        "actor_id": "reviewer-a",
        "occurred_at": datetime(2026, 9, 24, 8, 30, tzinfo=UTC),
        "payload": {"reviewer_id": "reviewer-a"},
        "previous_hash": "a" * 64,
    }
    original = event_hash(**parameters)  # type: ignore[arg-type]
    parameters[field] = changed
    assert event_hash(**parameters) != original  # type: ignore[arg-type]


def test_v2_canonical_boundaries_distinguish_adjacent_component_values() -> None:
    common: dict[str, object] = {
        "case_id": uuid.UUID("44444444-4444-4444-4444-444444444444"),
        "sequence_number": 2,
        "event_type": ReviewEventType.COMMENT_ADDED,
        "occurred_at": datetime(2026, 9, 24, 8, 30, tzinfo=UTC),
        "previous_hash": "c" * 64,
    }
    left = event_hash(**common, actor_id="ab", payload={"value": "c"})  # type: ignore[arg-type]
    right = event_hash(**common, actor_id="a", payload={"value": "bc"})  # type: ignore[arg-type]
    assert left != right
