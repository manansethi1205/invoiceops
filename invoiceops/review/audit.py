import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus

AUDIT_HASH_V1 = "review-audit-v1"
AUDIT_HASH_V2 = "review-audit-v2"


class UnsupportedAuditHashVersionError(ValueError):
    pass


def canonical_json(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_utc(value: datetime) -> str:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat(timespec="microseconds").replace("+00:00", "Z")


def event_hash(
    *,
    case_id: uuid.UUID,
    sequence_number: int,
    event_type: ReviewEventType,
    actor_id: str,
    occurred_at: datetime,
    payload: dict[str, object],
    previous_hash: str | None,
    hash_version: str = AUDIT_HASH_V2,
) -> str:
    if hash_version == AUDIT_HASH_V1:
        components = (
            str(case_id),
            str(sequence_number),
            event_type.value,
            actor_id,
            canonical_utc(occurred_at),
            canonical_json(payload),
            previous_hash or "",
        )
        canonical_content = "".join(components)
    elif hash_version == AUDIT_HASH_V2:
        envelope: dict[str, object] = {
            "hash_version": hash_version,
            "review_case_id": str(case_id),
            "sequence_number": sequence_number,
            "event_type": event_type.value,
            "actor_id": actor_id,
            "occurred_at": canonical_utc(occurred_at),
            "payload": payload,
            "previous_hash": previous_hash,
        }
        canonical_content = canonical_json(envelope)
    else:
        raise UnsupportedAuditHashVersionError(hash_version)
    return hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return canonical_utc(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Unsupported audit payload type: {type(value).__name__}")


@dataclass(frozen=True)
class ReconstructedState:
    status: ReviewStatus | None
    assignee: str | None
    resolution: ReviewResolution | None
    resolution_reason: str | None
    version: int


def apply_event(
    state: ReconstructedState,
    event_type: ReviewEventType,
    actor_id: str,
    payload: dict[str, object],
) -> ReconstructedState:
    version = state.version + 1
    if event_type == ReviewEventType.CASE_OPENED:
        return ReconstructedState(ReviewStatus.OPEN, None, None, None, version)
    if event_type == ReviewEventType.CASE_CLAIMED:
        return ReconstructedState(ReviewStatus.CLAIMED, actor_id, None, None, version)
    if event_type == ReviewEventType.COMMENT_ADDED:
        return ReconstructedState(
            state.status, state.assignee, state.resolution, state.resolution_reason, version
        )
    if event_type == ReviewEventType.CASE_RELEASED:
        return ReconstructedState(ReviewStatus.OPEN, None, None, None, version)
    resolution = ReviewResolution(str(payload.get("resolution")))
    reason = str(payload.get("reason", ""))
    return ReconstructedState(ReviewStatus.RESOLVED, actor_id, resolution, reason, version)
