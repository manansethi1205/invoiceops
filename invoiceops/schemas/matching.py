import re
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from invoiceops.schemas.extraction import EvidenceSpan


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("decimal values must be supplied as strings or integers, not floats")
    return value


def _non_blank(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


class MatchDecision(StrEnum):
    MATCHED = "MATCHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class CheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class CheckSeverity(StrEnum):
    INFO = "info"
    ERROR = "error"


class ReasonCode(StrEnum):
    INVOICE_SCHEMA_INCOMPLETE = "INVOICE_SCHEMA_INCOMPLETE"
    INVOICE_LINE_ARITHMETIC_MISMATCH = "INVOICE_LINE_ARITHMETIC_MISMATCH"
    INVOICE_SUBTOTAL_MISMATCH = "INVOICE_SUBTOTAL_MISMATCH"
    INVOICE_TOTAL_MISMATCH = "INVOICE_TOTAL_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    INVOICE_LINE_UNMATCHED = "INVOICE_LINE_UNMATCHED"
    PO_LINE_UNMATCHED = "PO_LINE_UNMATCHED"
    DESCRIPTION_BELOW_THRESHOLD = "DESCRIPTION_BELOW_THRESHOLD"
    DESCRIPTION_AMBIGUOUS = "DESCRIPTION_AMBIGUOUS"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    UNIT_PRICE_MISMATCH = "UNIT_PRICE_MISMATCH"
    EXTRA_INVOICE_LINE = "EXTRA_INVOICE_LINE"
    LINE_AMOUNT_MISMATCH = "LINE_AMOUNT_MISMATCH"
    NEGATIVE_AMOUNT = "NEGATIVE_AMOUNT"


class MatchingPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "matching-v1"
    amount_absolute_tolerance: Decimal = Field(default=Decimal("0.02"), ge=0)
    quantity_absolute_tolerance: Decimal = Field(default=Decimal("0"), ge=0)
    unit_price_relative_tolerance: Decimal = Field(default=Decimal("0.01"), ge=0)
    description_similarity_threshold: float = Field(default=0.85, ge=0, le=1)
    ambiguity_margin: float = Field(default=0.05, ge=0, le=1)

    @field_validator(
        "amount_absolute_tolerance",
        "quantity_absolute_tolerance",
        "unit_price_relative_tolerance",
        mode="before",
    )
    @classmethod
    def reject_float_tolerances(cls, value: object) -> object:
        return _reject_float(value)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _non_blank(value)


class PurchaseOrderLineCreate(BaseModel):
    line_number: str
    description: str
    ordered_quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)

    @field_validator("line_number", "description")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("ordered_quantity", "unit_price", mode="before")
    @classmethod
    def reject_float_decimals(cls, value: object) -> object:
        return _reject_float(value)


class PurchaseOrderCreate(BaseModel):
    external_po_number: str
    vendor_name: str | None = None
    currency: str
    lines: list[PurchaseOrderLineCreate] = Field(min_length=1)

    @field_validator("external_po_number")
    @classmethod
    def validate_po_number(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("vendor_name")
    @classmethod
    def normalize_vendor_name(cls, value: str | None) -> str | None:
        return None if value is None else _non_blank(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if re.fullmatch(r"[A-Z]{3}", normalized) is None:
            raise ValueError("currency must be a three-letter code")
        return normalized

    @model_validator(mode="after")
    def reject_duplicate_line_numbers(self) -> "PurchaseOrderCreate":
        line_numbers = [line.line_number for line in self.lines]
        if len(line_numbers) != len(set(line_numbers)):
            raise ValueError("purchase-order line numbers must be unique")
        return self


class PurchaseOrderLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_order_id: uuid.UUID
    line_number: str
    description: str
    ordered_quantity: Decimal
    unit_price: Decimal


class PurchaseOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_po_number: str
    vendor_name: str | None
    currency: str
    created_at: datetime
    lines: list[PurchaseOrderLineRead]


class ValidationCheck(BaseModel):
    code: ReasonCode
    status: CheckStatus
    severity: CheckSeverity
    expected: str | None = None
    actual: str | None = None
    tolerance: str | None = None
    message: str
    invoice_line_index: int | None = Field(default=None, ge=0)
    po_line_id: uuid.UUID | None = None
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class LineAssignment(BaseModel):
    invoice_line_index: int = Field(ge=0)
    po_line_id: uuid.UUID
    po_line_number: str
    description_score: float = Field(ge=0, le=1)
    exact_description: bool
    checks: list[ValidationCheck]
    evidence: list[EvidenceSpan] = Field(default_factory=list)


class MatchSummary(BaseModel):
    invoice_line_count: int = Field(ge=0)
    po_line_count: int = Field(ge=0)
    assigned_line_count: int = Field(ge=0)
    passed_check_count: int = Field(ge=0)
    failed_check_count: int = Field(ge=0)


class MatchResult(BaseModel):
    decision: MatchDecision
    summary: MatchSummary
    checks: list[ValidationCheck]
    line_assignments: list[LineAssignment]
    reason_codes: list[ReasonCode]

    @model_validator(mode="after")
    def validate_decision_contract(self) -> "MatchResult":
        failures = [check for check in self.checks if check.status == CheckStatus.FAILED]
        failures.extend(
            check
            for assignment in self.line_assignments
            for check in assignment.checks
            if check.status == CheckStatus.FAILED
        )
        if self.decision == MatchDecision.MATCHED and (failures or self.reason_codes):
            raise ValueError("MATCHED cannot contain failures or reason codes")
        if self.decision == MatchDecision.NEEDS_REVIEW and (
            not failures or not self.reason_codes
        ):
            raise ValueError("NEEDS_REVIEW requires failed checks and reason codes")
        return self


class MatchCreate(BaseModel):
    purchase_order_id: uuid.UUID


class MatchRunRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    purchase_order_id: uuid.UUID
    extraction_run_id: uuid.UUID
    policy_version: str
    policy_snapshot: MatchingPolicy
    decision: MatchDecision
    result: MatchResult
    created_at: datetime
