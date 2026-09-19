from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TextSource(StrEnum):
    EMBEDDED = "embedded_text"
    OCR = "ocr"


class OcrReason(StrEnum):
    EMBEDDED_TEXT_SUFFICIENT = "embedded_text_sufficient"
    NO_EMBEDDED_TEXT = "no_embedded_text"
    TOO_FEW_EMBEDDED_WORDS = "too_few_embedded_words"
    EMBEDDED_TEXT_TOO_SHORT = "embedded_text_too_short"


class ExtractionStatus(StrEnum):
    EXTRACTED = "extracted"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_coordinate_order(self) -> "BoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding-box maximums must not be smaller than minimums")
        return self


class EvidenceSpan(BaseModel):
    page: int = Field(ge=0)
    bbox: BoundingBox
    text: str
    source: TextSource


class ExtractedField[T](BaseModel):
    value: T | None
    status: ExtractionStatus
    evidence: list[EvidenceSpan]
    rule_id: str | None = None

    @model_validator(mode="after")
    def validate_status_contract(self) -> "ExtractedField[T]":
        if self.status == ExtractionStatus.EXTRACTED:
            if self.value is None:
                raise ValueError("an extracted field must contain a value")
            if not self.evidence:
                raise ValueError("an extracted field must contain evidence")
        if self.status == ExtractionStatus.MISSING and self.value is not None:
            raise ValueError("a missing field cannot contain a value")
        return self


class InvoiceLine(BaseModel):
    description: ExtractedField[str]
    quantity: ExtractedField[Decimal]
    unit_price: ExtractedField[Decimal]
    line_total: ExtractedField[Decimal]


class Invoice(BaseModel):
    invoice_number: ExtractedField[str]
    invoice_date: ExtractedField[date]
    currency: ExtractedField[str]
    subtotal: ExtractedField[Decimal]
    tax: ExtractedField[Decimal]
    total: ExtractedField[Decimal]
    line_items: list[InvoiceLine]


class WordToken(BaseModel):
    text: str
    page: int = Field(ge=0)
    bbox: BoundingBox
    block_number: int = Field(ge=0)
    line_number: int = Field(ge=0)
    word_number: int = Field(ge=0)
    source: TextSource


class PageText(BaseModel):
    page: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    source: TextSource
    ocr_reason: OcrReason
    words: list[WordToken]


class DocumentText(BaseModel):
    pages: list[PageText]
    used_ocr: bool
