from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoiceops.schemas.extraction import Invoice


class GroundTruthLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class GroundTruthInvoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[GroundTruthLineItem] = Field(default_factory=list)


class EvaluationExample(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1)
    split: Literal["development", "holdout"]
    document_path: Path
    content_type: Literal["application/pdf", "image/png", "image/jpeg"]
    ground_truth_path: Path
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def paths_must_be_relative(self) -> "EvaluationExample":
        if self.document_path.is_absolute() or self.ground_truth_path.is_absolute():
            raise ValueError("evaluation manifest paths must be relative")
        return self


class EvaluationPrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    invoice: Invoice | None
    schema_valid: bool
    used_ocr: bool
    page_count: int | None = Field(default=None, ge=0)
    latency_ms: float = Field(ge=0)
    error_code: str | None = None


class EvaluationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    example: EvaluationExample
    ground_truth: GroundTruthInvoice
    prediction: EvaluationPrediction
    document_sha256: str
    ground_truth_sha256: str
