import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from invoiceops.review.audit import canonical_json, event_hash
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
