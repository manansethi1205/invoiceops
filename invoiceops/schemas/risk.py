import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("decimal values must be supplied as strings or integers, not floats")
    return value


class RiskDisposition(StrEnum):
    CLEAR = "CLEAR"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    NOT_ASSESSABLE = "NOT_ASSESSABLE"


class RiskSignalCode(StrEnum):
    EXACT_BUSINESS_KEY_DUPLICATE = "EXACT_BUSINESS_KEY_DUPLICATE"
    REUSED_VENDOR_INVOICE_NUMBER = "REUSED_VENDOR_INVOICE_NUMBER"
    SAME_PO_INVOICE_REPLAY = "SAME_PO_INVOICE_REPLAY"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    DUPLICATE_CHECK_INCOMPLETE = "DUPLICATE_CHECK_INCOMPLETE"


class RiskSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DuplicateRiskPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = "duplicate-risk-v1"
    amount_absolute_tolerance: Decimal = Field(default=Decimal("0.02"), ge=0)
    date_window_days: int = Field(default=7, ge=0)
    invoice_number_similarity_threshold: Decimal = Field(
        default=Decimal("0.92"), ge=0, le=1
    )
    route_incomplete_to_review: bool = True

    @field_validator(
        "amount_absolute_tolerance",
        "invoice_number_similarity_threshold",
        mode="before",
    )
    @classmethod
    def reject_float_decimals(cls, value: object) -> object:
        return _reject_float(value)

    @field_serializer("amount_absolute_tolerance", "invoice_number_similarity_threshold")
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")


class RiskFeatureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    normalized_vendor: str | None
    normalized_invoice_number: str | None
    invoice_date: date | None
    currency: str | None
    total: str | None
    purchase_order_id: uuid.UUID
    document_id: uuid.UUID
    extraction_run_id: uuid.UUID
    match_run_id: uuid.UUID
    missing_fields: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_fields


class RiskSignalDraft(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: RiskSignalCode
    severity: RiskSeverity
    comparison_match_run_id: uuid.UUID | None = None
    observed: dict[str, object]
    reference: dict[str, object]
    explanation: str


class RiskAssessmentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    disposition: RiskDisposition
    features: RiskFeatureSnapshot
    signals: tuple[RiskSignalDraft, ...]


class RiskSignalRead(BaseModel):
    id: uuid.UUID
    code: RiskSignalCode
    severity: RiskSeverity
    comparison_match_run_id: uuid.UUID | None
    observed: dict[str, object]
    reference: dict[str, object]
    explanation: str
    created_at: datetime


class RiskAssessmentRead(BaseModel):
    id: uuid.UUID
    match_run_id: uuid.UUID
    policy_version: str
    policy_snapshot: DuplicateRiskPolicy
    disposition: RiskDisposition
    feature_snapshot: RiskFeatureSnapshot
    feature_complete: bool
    signals: list[RiskSignalRead]
    compared_match_run_ids: list[uuid.UUID]
    match_decision: str
    review_case_id: uuid.UUID | None
    review_status: str | None
    human_resolution: str | None
    payment_authorized: bool = False
    created_at: datetime
