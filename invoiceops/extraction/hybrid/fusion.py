from dataclasses import dataclass

from invoiceops.extraction.hybrid.grounding import GroundingResult, ground_candidate
from invoiceops.extraction.hybrid.schemas import (
    FusionOutcome,
    VisionInvoiceCandidate,
)
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
)

HEADER_FIELDS = ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")
LINE_FIELDS = ("description", "quantity", "unit_price", "line_total")


@dataclass(frozen=True)
class FusionResult:
    invoice: Invoice
    outcomes: dict[str, FusionOutcome]
    grounding: dict[str, str]


def _fuse_field(
    deterministic: ExtractedField[object],
    grounded: GroundingResult,
    *,
    path: str,
    outcomes: dict[str, FusionOutcome],
) -> ExtractedField[object]:
    if not grounded.grounded or grounded.normalized_value is None:
        outcomes[path] = FusionOutcome.UNGROUNDED_REJECTED
        return deterministic
    if deterministic.status == ExtractionStatus.EXTRACTED:
        if deterministic.value == grounded.normalized_value:
            outcomes[path] = FusionOutcome.AGREEMENT
            return deterministic
        outcomes[path] = FusionOutcome.DISAGREEMENT_ABSTAINED
        return ExtractedField[object](
            value=None,
            status=ExtractionStatus.AMBIGUOUS,
            evidence=list(deterministic.evidence) + list(grounded.evidence),
            rule_id="fusion.invoice-vision-v1.disagreement",
        )
    outcomes[path] = FusionOutcome.VLM_FILLED
    return ExtractedField[object](
        value=grounded.normalized_value,
        status=ExtractionStatus.EXTRACTED,
        evidence=list(grounded.evidence),
        rule_id="vlm.invoice-vision-v1.grounded",
    )


def fuse_invoice(
    deterministic: Invoice,
    candidate: VisionInvoiceCandidate,
    document: DocumentText,
    *,
    fuzzy_threshold: float = 92.0,
) -> FusionResult:
    outcomes: dict[str, FusionOutcome] = {}
    grounding: dict[str, str] = {}
    values: dict[str, object] = {}
    for name in HEADER_FIELDS:
        candidate_field = getattr(candidate, name)
        if candidate_field.raw_value is None:
            values[name] = getattr(deterministic, name)
            outcomes[name] = FusionOutcome.DETERMINISTIC_ONLY
            continue
        result = ground_candidate(name, candidate_field, document, fuzzy_threshold=fuzzy_threshold)
        grounding[name] = result.reason.value
        values[name] = _fuse_field(
            getattr(deterministic, name), result, path=name, outcomes=outcomes
        )

    lines: list[InvoiceLine] = []
    line_count = max(len(deterministic.line_items), len(candidate.line_items))
    for index in range(line_count):
        deterministic_line = (
            deterministic.line_items[index] if index < len(deterministic.line_items) else None
        )
        candidate_line = candidate.line_items[index] if index < len(candidate.line_items) else None
        if candidate_line is None and deterministic_line is not None:
            lines.append(deterministic_line)
            for name in LINE_FIELDS:
                outcomes[f"line_items.{index}.{name}"] = FusionOutcome.DETERMINISTIC_ONLY
            continue
        fields: dict[str, object] = {}
        for name in LINE_FIELDS:
            path = f"line_items.{index}.{name}"
            if deterministic_line is None:
                deterministic_field = ExtractedField[object](
                    value=None, status=ExtractionStatus.MISSING, evidence=[]
                )
            else:
                deterministic_field = getattr(deterministic_line, name)
            if candidate_line is None:
                fields[name] = deterministic_field
                continue
            candidate_field = getattr(candidate_line, name)
            if candidate_field.raw_value is None:
                fields[name] = deterministic_field
                outcomes[path] = FusionOutcome.DETERMINISTIC_ONLY
                continue
            result = ground_candidate(
                name, candidate_field, document, fuzzy_threshold=fuzzy_threshold
            )
            grounding[path] = result.reason.value
            fields[name] = _fuse_field(deterministic_field, result, path=path, outcomes=outcomes)
        lines.append(InvoiceLine.model_validate(fields))
    values["line_items"] = lines
    return FusionResult(Invoice.model_validate(values), outcomes, grounding)
