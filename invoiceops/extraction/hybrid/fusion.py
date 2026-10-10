from dataclasses import dataclass

from invoiceops.extraction.hybrid.grounding import GroundingResult, ground_candidate
from invoiceops.extraction.hybrid.schemas import (
    FusionOutcome,
    VisionInvoiceCandidate,
)
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionIssue,
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
    row_associations: dict[int, int]


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

    # Ground every claimed cell before considering row identity.
    from invoiceops.extraction.hybrid.row_association import associate_rows

    rows = [
        {
            name: ground_candidate(
                name, getattr(row, name), document, fuzzy_threshold=fuzzy_threshold
            )
            for name in LINE_FIELDS
            if getattr(row, name).raw_value is not None
        }
        for row in candidate.line_items
    ]
    associations, reasons = associate_rows(deterministic.line_items, rows, document)
    for candidate_index, reason in enumerate(reasons):
        grounding[f"candidate_rows.{candidate_index}"] = reason
        for name, result in rows[candidate_index].items():
            grounding[f"candidate_rows.{candidate_index}.{name}"] = result.reason.value
    issues = list(deterministic.extraction_issues)
    if any(reason != "associated" for reason in reasons) or (
        deterministic.line_items and len(associations) != len(deterministic.line_items)
    ):
        issue = ExtractionIssue.HYBRID_ROW_ASSOCIATION_UNRESOLVED
        if issue not in issues:
            issues.append(issue)
    lines: list[InvoiceLine] = []
    for index, deterministic_line in enumerate(deterministic.line_items):
        associated_index = associations.get(index)
        fields: dict[str, object] = {}
        for name in LINE_FIELDS:
            path = f"line_items.{index}.{name}"
            field = getattr(deterministic_line, name)
            if associated_index is None or name not in rows[associated_index]:
                fields[name] = field
                outcomes[path] = FusionOutcome.DETERMINISTIC_ONLY
            else:
                grounding[path] = rows[associated_index][name].reason.value
                fields[name] = _fuse_field(
                    field, rows[associated_index][name], path=path, outcomes=outcomes
                )
        lines.append(InvoiceLine.model_validate(fields))
    values["extraction_issues"] = issues
    values["line_items"] = lines
    return FusionResult(Invoice.model_validate(values), outcomes, grounding, associations)
