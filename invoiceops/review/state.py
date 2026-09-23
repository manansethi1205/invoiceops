from dataclasses import dataclass

from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus


class ReviewTransitionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReviewState:
    status: ReviewStatus
    assignee: str | None
    version: int
    resolution: ReviewResolution | None = None
    resolution_reason: str | None = None


@dataclass(frozen=True)
class Transition:
    event_type: ReviewEventType
    status: ReviewStatus
    assignee: str | None
    resolution: ReviewResolution | None
    resolution_reason: str | None
    payload: dict[str, object]


def validate_expected_version(state: ReviewState, expected_version: int) -> None:
    if expected_version != state.version:
        raise ReviewTransitionError("STALE_VERSION", "The review case version is stale")


def claim(state: ReviewState, actor_id: str, expected_version: int) -> Transition:
    validate_expected_version(state, expected_version)
    if state.status != ReviewStatus.OPEN:
        raise ReviewTransitionError("INVALID_TRANSITION", "Only an open case can be claimed")
    return Transition(
        ReviewEventType.CASE_CLAIMED,
        ReviewStatus.CLAIMED,
        actor_id,
        None,
        None,
        {"reviewer_id": actor_id},
    )


def release(
    state: ReviewState, actor_id: str, expected_version: int, reason: str
) -> Transition:
    validate_expected_version(state, expected_version)
    _require_assigned_claim(state, actor_id)
    return Transition(
        ReviewEventType.CASE_RELEASED,
        ReviewStatus.OPEN,
        None,
        None,
        None,
        {"reason": reason},
    )


def comment(
    state: ReviewState, actor_id: str, expected_version: int, text: str
) -> Transition:
    validate_expected_version(state, expected_version)
    if state.status == ReviewStatus.RESOLVED:
        raise ReviewTransitionError("CASE_RESOLVED", "A resolved case cannot be changed")
    return Transition(
        ReviewEventType.COMMENT_ADDED,
        state.status,
        state.assignee,
        state.resolution,
        state.resolution_reason,
        {"comment": text},
    )


def resolve(
    state: ReviewState,
    actor_id: str,
    expected_version: int,
    resolution: ReviewResolution,
    reason: str,
) -> Transition:
    validate_expected_version(state, expected_version)
    _require_assigned_claim(state, actor_id)
    if not reason.strip():
        raise ReviewTransitionError(
            "RESOLUTION_REASON_REQUIRED", "Resolution requires an explanation"
        )
    return Transition(
        ReviewEventType.CASE_RESOLVED,
        ReviewStatus.RESOLVED,
        actor_id,
        resolution,
        reason.strip(),
        {"resolution": resolution.value, "reason": reason.strip()},
    )


def _require_assigned_claim(state: ReviewState, actor_id: str) -> None:
    if state.status == ReviewStatus.RESOLVED:
        raise ReviewTransitionError("CASE_RESOLVED", "A resolved case cannot be changed")
    if state.status != ReviewStatus.CLAIMED:
        raise ReviewTransitionError("INVALID_TRANSITION", "The case must be claimed first")
    if state.assignee != actor_id:
        raise ReviewTransitionError(
            "REVIEWER_OWNERSHIP_CONFLICT", "Only the assigned reviewer can perform this action"
        )
