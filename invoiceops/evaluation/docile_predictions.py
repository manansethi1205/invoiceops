import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.evaluation.docile_mapping import (
    DOCILE_KILE_TO_INVOICEOPS,
    DOCILE_LIR_TO_INVOICEOPS,
)
from invoiceops.schemas.extraction import EvidenceSpan, ExtractedField, ExtractionStatus, Invoice


class DocilePrediction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: int = Field(ge=0)
    bbox: tuple[float, float, float, float]
    fieldtype: str
    text: str
    line_item_id: int | None = Field(default=None, ge=0)


def _normalized_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def _union_evidence(
    evidence: list[EvidenceSpan],
) -> tuple[int, tuple[float, float, float, float]] | None:
    if not evidence:
        return None
    pages = {span.page for span in evidence}
    if len(pages) != 1:
        return None
    return (
        evidence[0].page,
        (
            min(span.bbox.x0 for span in evidence),
            min(span.bbox.y0 for span in evidence),
            max(span.bbox.x1 for span in evidence),
            max(span.bbox.y1 for span in evidence),
        ),
    )


def _prediction(
    field: ExtractedField[Any],
    *,
    fieldtype: str,
    line_item_id: int | None = None,
) -> DocilePrediction | None:
    if field.status != ExtractionStatus.EXTRACTED or field.value is None:
        return None
    location = _union_evidence(field.evidence)
    if location is None:
        return None
    page, bbox = location
    return DocilePrediction(
        page=page,
        bbox=bbox,
        fieldtype=fieldtype,
        text=_normalized_text(field.value),
        line_item_id=line_item_id,
    )


def invoice_to_docile_predictions(
    invoice: Invoice,
) -> tuple[list[DocilePrediction], list[DocilePrediction]]:
    kile: list[DocilePrediction] = []
    for docile_field, invoiceops_field in DOCILE_KILE_TO_INVOICEOPS.items():
        converted = _prediction(getattr(invoice, invoiceops_field), fieldtype=docile_field)
        if converted is not None:
            kile.append(converted)
    lir: list[DocilePrediction] = []
    for line_item_id, line in enumerate(invoice.line_items):
        for docile_field, invoiceops_field in DOCILE_LIR_TO_INVOICEOPS.items():
            converted = _prediction(
                getattr(line, invoiceops_field),
                fieldtype=docile_field,
                line_item_id=line_item_id,
            )
            if converted is not None:
                lir.append(converted)
    return kile, lir


def write_docile_predictions(
    path: Path, predictions: dict[str, list[DocilePrediction]]
) -> None:
    payload = {
        document_id: [prediction.model_dump(exclude_none=True) for prediction in fields]
        for document_id, fields in sorted(predictions.items())
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
