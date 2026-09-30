import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from invoiceops.schemas.extraction import ExtractedField, Invoice
from invoiceops.schemas.matching import PurchaseOrderCreate


class CaseStatus(StrEnum):
    DRAFT = "DRAFT"
    PROCESSING = "PROCESSING"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    READY_TO_MATCH = "READY_TO_MATCH"
    MATCHED = "MATCHED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class DocumentRole(StrEnum):
    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    GOODS_RECEIPT = "GOODS_RECEIPT"
    DELIVERY_NOTE = "DELIVERY_NOTE"


class ConfirmationStatus(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"


class SupportingExtractionStatus(StrEnum):
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return value.strip()


class CaseRead(BaseModel):
    id: uuid.UUID
    case_number: str
    status: CaseStatus
    version: int
    created_at: datetime
    updated_at: datetime


class CaseDocumentRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    document_id: uuid.UUID
    job_id: uuid.UUID
    role: DocumentRole
    filename: str
    content_type: str
    byte_size: int
    attachment_order: int
    supersedes_id: uuid.UUID | None
    is_active: bool
    job_status: str
    extraction_status: SupportingExtractionStatus | None
    confirmation_status: ConfirmationStatus
    created_at: datetime


class CaseAttachmentAccepted(BaseModel):
    case: CaseRead
    attachment: CaseDocumentRead
    deduplicated_document: bool
    replayed: bool


class CaseEventRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    sequence: int
    event_type: str
    stage: str
    status: str
    message: str
    document_id: uuid.UUID | None
    document_role: DocumentRole | None
    payload: dict[str, object]
    occurred_at: datetime


class ExtractedPurchaseOrderLine(BaseModel):
    line_number: ExtractedField[str]
    description: ExtractedField[str]
    ordered_quantity: ExtractedField[Decimal]
    unit_price: ExtractedField[Decimal]
    line_total: ExtractedField[Decimal]


class ExtractedPurchaseOrder(BaseModel):
    po_number: ExtractedField[str]
    issue_date: ExtractedField[date]
    vendor: ExtractedField[str]
    buyer: ExtractedField[str]
    currency: ExtractedField[str]
    subtotal: ExtractedField[Decimal]
    tax: ExtractedField[Decimal]
    total: ExtractedField[Decimal]
    line_items: list[ExtractedPurchaseOrderLine]


class ExtractedGoodsReceiptLine(BaseModel):
    description: ExtractedField[str]
    received_quantity: ExtractedField[Decimal]
    accepted_quantity: ExtractedField[Decimal]
    rejected_quantity: ExtractedField[Decimal]


class ExtractedGoodsReceipt(BaseModel):
    receipt_number: ExtractedField[str]
    referenced_po_number: ExtractedField[str]
    received_date: ExtractedField[date]
    supplier: ExtractedField[str]
    line_items: list[ExtractedGoodsReceiptLine]


class SupportingExtractionRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    role: DocumentRole
    extractor_name: str
    extractor_version: str
    schema_version: str
    status: SupportingExtractionStatus
    output: ExtractedPurchaseOrder | ExtractedGoodsReceipt | None
    used_ocr: bool | None
    latency_ms: float | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class CaseExtractionRead(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    role: DocumentRole
    extractor_name: str
    extractor_version: str
    schema_version: str
    status: str
    output: Invoice | ExtractedPurchaseOrder | ExtractedGoodsReceipt | None
    used_ocr: bool | None
    latency_ms: float | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class PurchaseOrderConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_case_version: int = Field(ge=1)
    extraction_run_id: uuid.UUID
    extractor_version: str = Field(min_length=1, max_length=50)
    confirmed: "PurchaseOrderConfirmationValues"
    correction_reason: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("idempotency_key", "correction_reason")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PurchaseOrderConfirmationValues(PurchaseOrderCreate):
    issue_date: date | None = None
    buyer_name: str | None = Field(default=None, max_length=255)
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax: Decimal | None = Field(default=None, ge=0)
    total: Decimal | None = Field(default=None, ge=0)

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def reject_float_money(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("decimal values must be strings or integers")
        return value

    @model_validator(mode="after")
    def validate_totals(self) -> "PurchaseOrderConfirmationValues":
        if self.subtotal is None or self.total is None:
            return self
        tax = self.tax or Decimal("0")
        tax_exclusive = abs(self.subtotal + tax - self.total) <= Decimal("0.02")
        tax_inclusive = abs(self.subtotal - self.total) <= Decimal("0.02")
        if not tax_exclusive and not tax_inclusive:
            raise ValueError("PO totals are not arithmetically consistent")
        return self


class ReceiptConfirmationLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_line_number: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1, max_length=500)
    received_quantity: Decimal = Field(gt=0)
    accepted_quantity: Decimal = Field(gt=0)
    rejected_quantity: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("received_quantity", "accepted_quantity", "rejected_quantity", mode="before")
    @classmethod
    def reject_float(cls, value: object) -> object:
        if isinstance(value, float):
            raise ValueError("decimal values must be strings or integers")
        return value

    @model_validator(mode="after")
    def quantities_reconcile(self) -> "ReceiptConfirmationLine":
        if self.accepted_quantity + self.rejected_quantity != self.received_quantity:
            raise ValueError("accepted plus rejected quantity must equal received quantity")
        return self


class ReceiptConfirmationValues(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_receipt_number: str = Field(min_length=1, max_length=100)
    referenced_po_number: str = Field(min_length=1, max_length=100)
    supplier: str | None = Field(default=None, max_length=255)
    received_at: datetime
    lines: list[ReceiptConfirmationLine] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_line_numbers(self) -> "ReceiptConfirmationValues":
        numbers = [item.purchase_order_line_number.strip() for item in self.lines]
        if len(numbers) != len(set(numbers)):
            raise ValueError("purchase-order line numbers must be unique")
        return self


class ReceiptConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_case_version: int = Field(ge=1)
    extraction_run_id: uuid.UUID
    extractor_version: str = Field(min_length=1, max_length=50)
    confirmed: ReceiptConfirmationValues
    correction_reason: str | None = Field(default=None, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CaseMatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_case_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ConfirmationRead(BaseModel):
    id: uuid.UUID
    case_document_id: uuid.UUID
    extraction_run_id: uuid.UUID
    canonical_record_type: str
    canonical_record_id: uuid.UUID
    corrected_fields: list[str]
    correction_reason: str | None
    created_at: datetime
