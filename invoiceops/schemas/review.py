import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from invoiceops.schemas.matching import MatchRunRead, ReasonCode


class ReviewStatus(StrEnum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    RESOLVED = "RESOLVED"


class ReviewResolution(StrEnum):
    ACCEPTED_EXCEPTION = "ACCEPTED_EXCEPTION"
    REJECTED_DOCUMENT = "REJECTED_DOCUMENT"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"


class ReviewEventType(StrEnum):
    CASE_OPENED = "CASE_OPENED"
    CASE_CLAIMED = "CASE_CLAIMED"
    COMMENT_ADDED = "COMMENT_ADDED"
    CASE_RELEASED = "CASE_RELEASED"
    CASE_RESOLVED = "CASE_RESOLVED"


class ReviewTriggerType(StrEnum):
    MATCH_REASON = "MATCH_REASON"
    RISK_SIGNAL = "RISK_SIGNAL"


class ReviewTriggerRead(BaseModel):
    id: uuid.UUID
    type: ReviewTriggerType
    code: str
    source_id: uuid.UUID
    source_url: str
    created_at: datetime


class VersionedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ReleaseCommand(VersionedCommand):
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason must not be blank")
        return value.strip()


class CommentCommand(VersionedCommand):
    comment: str = Field(min_length=1, max_length=4000)

    @field_validator("comment")
    @classmethod
    def comment_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment must not be blank")
        return value.strip()


class ResolveCommand(VersionedCommand):
    resolution: ReviewResolution
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resolution reason must not be blank")
        return value.strip()


class ReviewCaseRead(BaseModel):
    id: uuid.UUID
    match_run_id: uuid.UUID
    status: ReviewStatus
    assigned_reviewer_id: str | None
    version: int
    opened_at: datetime
    claimed_at: datetime | None
    resolved_at: datetime | None
    resolution: ReviewResolution | None
    resolution_reason: str | None
    reason_codes: list[ReasonCode]
    review_triggers: list[ReviewTriggerRead]


class ReviewCaseDetail(ReviewCaseRead):
    match: MatchRunRead
    extraction_name: str
    extraction_version: str
    events_url: str
    audit_verification_url: str


class ReviewCasePage(BaseModel):
    items: list[ReviewCaseRead]
    next_cursor: str | None


class ReviewEventRead(BaseModel):
    id: uuid.UUID
    review_case_id: uuid.UUID
    sequence_number: int
    event_type: ReviewEventType
    actor_id: str
    payload: dict[str, object]
    hash_version: str
    previous_hash: str | None
    event_hash: str
    occurred_at: datetime


class AuditVerificationRead(BaseModel):
    review_case_id: uuid.UUID
    valid: bool
    event_count: int
    last_sequence_number: int
    errors: list[str]
    reconstructed_status: ReviewStatus | None
    reconstructed_assignee: str | None
    reconstructed_resolution: ReviewResolution | None
    reconstructed_resolution_reason: str | None
    reconstructed_version: int
    reconstructed_opening_triggers: list[dict[str, object]]


class ReviewErrorBody(BaseModel):
    code: str
    message: str
