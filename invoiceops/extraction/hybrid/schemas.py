from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RoutingReason(StrEnum):
    CRITICAL_FIELD_MISSING = "CRITICAL_FIELD_MISSING"
    CRITICAL_FIELD_AMBIGUOUS = "CRITICAL_FIELD_AMBIGUOUS"
    NO_LINE_ITEMS = "NO_LINE_ITEMS"
    INCOMPLETE_LINE_ITEMS = "INCOMPLETE_LINE_ITEMS"
    HEADER_ARITHMETIC_CONTRADICTION = "HEADER_ARITHMETIC_CONTRADICTION"
    LINE_ARITHMETIC_CONTRADICTION = "LINE_ARITHMETIC_CONTRADICTION"
    OCR_HEAVY_DOCUMENT = "OCR_HEAVY_DOCUMENT"


class RoutingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invoke_vlm: bool
    reasons: list[RoutingReason]
    deterministic_completeness: float = Field(ge=0, le=1)
    critical_field_completeness: float = Field(ge=0, le=1)
    complete_line_item_ratio: float = Field(ge=0, le=1)


class CandidateField(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_value: str | None
    page: int | None = Field(default=None, ge=0)
    evidence_quote: str | None
    confidence: float | None = Field(default=None, ge=0, le=1)


class CandidateLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: CandidateField
    quantity: CandidateField
    unit_price: CandidateField
    line_total: CandidateField


class VisionInvoiceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invoice_number: CandidateField
    invoice_date: CandidateField
    currency: CandidateField
    subtotal: CandidateField
    tax: CandidateField
    total: CandidateField
    line_items: list[CandidateLineItem]


class RenderedPage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=0)
    mime_type: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    image_bytes: bytes


class VisionUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class VisionExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: VisionInvoiceCandidate
    response_id: str | None = None
    returned_model: str | None = None
    usage: VisionUsage = Field(default_factory=VisionUsage)
    latency_ms: float = Field(ge=0)


class GroundingReason(StrEnum):
    GROUNDED_EXACT = "GROUNDED_EXACT"
    GROUNDED_FUZZY = "GROUNDED_FUZZY"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    QUOTE_NOT_UNIQUE = "QUOTE_NOT_UNIQUE"
    PAGE_OUT_OF_RANGE = "PAGE_OUT_OF_RANGE"
    VALUE_NORMALIZATION_FAILED = "VALUE_NORMALIZATION_FAILED"


class FusionOutcome(StrEnum):
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"
    AGREEMENT = "AGREEMENT"
    VLM_FILLED = "VLM_FILLED"
    DISAGREEMENT_ABSTAINED = "DISAGREEMENT_ABSTAINED"
    UNGROUNDED_REJECTED = "UNGROUNDED_REJECTED"
