"""Private human labels; deliberately separate from legacy truth and production schemas."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoiceops.evaluation.metrics import HEADER_FIELDS
from invoiceops.evaluation.schemas import GroundTruthInvoice, GroundTruthLineItem
from invoiceops.schemas.extraction import BoundingBox

type LabelStatus = Literal["present", "absent", "not_annotated"]


class LabelEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    page: int = Field(ge=0)
    bbox: BoundingBox

    @model_validator(mode="after")
    def positive_area(self) -> "LabelEvidence":
        if self.bbox.x0 == self.bbox.x1 or self.bbox.y0 == self.bbox.y1:
            raise ValueError("Human evidence must have positive area")
        return self


class HumanField[T](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: LabelStatus = "not_annotated"
    value: T | None = None
    evidence: list[LabelEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_label(self) -> "HumanField[T]":
        if self.status == "present":
            if self.value is None or not self.evidence:
                raise ValueError("Present human labels require a value and source box")
            if isinstance(self.value, str) and not self.value.strip():
                raise ValueError("Present labels cannot be blank")
            if isinstance(self.value, Decimal) and not self.value.is_finite():
                raise ValueError("Financial labels must be finite")
        elif self.value is not None or self.evidence:
            raise ValueError("Absent/unannotated labels cannot contain a value or evidence")
        return self


class HumanLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: HumanField[str] = Field(default_factory=HumanField[str])
    quantity: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    unit_price: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    line_total: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])


class HumanLines(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: LabelStatus = "not_annotated"
    rows: list[HumanLine] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_rows(self) -> "HumanLines":
        if (self.status == "present") != bool(self.rows):
            raise ValueError("Only present item tables contain labelled rows")
        return self


class HumanInvoiceAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    annotation_version: Literal["human-invoice-v1"]
    provenance: Literal["human"]
    invoice_number: HumanField[str] = Field(default_factory=HumanField[str])
    invoice_date: HumanField[date] = Field(default_factory=HumanField[date])
    currency: HumanField[str] = Field(default_factory=HumanField[str])
    subtotal: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    tax: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    total: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    line_items: HumanLines = Field(default_factory=HumanLines)

    def legacy_truth(self) -> GroundTruthInvoice:
        return GroundTruthInvoice.model_validate(
            {
                **{name: getattr(self, name).value for name in HEADER_FIELDS},
                "line_items": [
                    GroundTruthLineItem.model_validate({name: field.value for name, field in row})
                    for row in self.line_items.rows
                ],
            }
        )
