"""Pure, conservative candidate routing and grounding for supporting proofs."""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.extraction.hybrid.schemas import CandidateField, GroundingReason, VisionUsage
from invoiceops.extraction.normalization import (
    normalize_currency,
    normalize_identifier,
    parse_invoice_date,
    parse_money,
)
from invoiceops.extraction.supporting_quote_grounding import locate_supporting_quote
from invoiceops.extraction.table_layout import reconstruct_visual_rows
from invoiceops.schemas.cases import (
    DocumentRole,
    ExtractedGoodsReceipt,
    ExtractedGoodsReceiptLine,
    ExtractedPurchaseOrder,
    ExtractedPurchaseOrderLine,
)
from invoiceops.schemas.extraction import DocumentText, ExtractedField, ExtractionStatus

SUPPORTING_HYBRID_NAME = "supporting-hybrid-routed"
SUPPORTING_HYBRID_VERSION = "0.4.0"
PO_PROMPT_VERSION = "supporting-po-vision-v1"
RECEIPT_PROMPT_VERSION = "supporting-receipt-vision-v1"
DELIVERY_PROMPT_VERSION = "supporting-delivery-vision-v1"


class SupportingRouteReason(StrEnum):
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    REQUIRED_FIELD_AMBIGUOUS = "REQUIRED_FIELD_AMBIGUOUS"
    INCOMPLETE_LINE_ITEMS = "INCOMPLETE_LINE_ITEMS"
    NO_LINE_ITEMS = "NO_LINE_ITEMS"
    TOTAL_CONFLICT = "TOTAL_CONFLICT"
    QUANTITY_ASSOCIATION_INCOMPLETE = "QUANTITY_ASSOCIATION_INCOMPLETE"
    OCR_REQUIRED_FIELD = "OCR_REQUIRED_FIELD"


class SupportingRoute(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    invoke_model: bool
    reasons: list[SupportingRouteReason]


class PurchaseOrderLineCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_number: CandidateField
    description: CandidateField
    ordered_quantity: CandidateField
    unit_price: CandidateField
    line_total: CandidateField


class PurchaseOrderCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    po_number: CandidateField
    issue_date: CandidateField
    vendor: CandidateField
    buyer: CandidateField
    currency: CandidateField
    subtotal: CandidateField
    tax: CandidateField
    total: CandidateField
    line_items: list[PurchaseOrderLineCandidate]


class GoodsReceiptLineCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    description: CandidateField
    received_quantity: CandidateField
    accepted_quantity: CandidateField
    rejected_quantity: CandidateField


class GoodsReceiptCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_number: CandidateField
    referenced_po_number: CandidateField
    received_date: CandidateField
    supplier: CandidateField
    line_items: list[GoodsReceiptLineCandidate]


class DeliveryNoteCandidate(GoodsReceiptCandidate):
    """Separate role contract; fields map to current receipt confirmation semantics."""


def candidate_schema(
    role: DocumentRole,
) -> type[PurchaseOrderCandidate] | type[GoodsReceiptCandidate] | type[DeliveryNoteCandidate]:
    if role == DocumentRole.PURCHASE_ORDER:
        return PurchaseOrderCandidate
    if role == DocumentRole.GOODS_RECEIPT:
        return GoodsReceiptCandidate
    if role == DocumentRole.DELIVERY_NOTE:
        return DeliveryNoteCandidate
    raise ValueError("unsupported supporting role")


class SupportingResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate: PurchaseOrderCandidate | GoodsReceiptCandidate | DeliveryNoteCandidate
    response_id: str | None = None
    returned_model: str | None = None
    usage: VisionUsage = Field(default_factory=VisionUsage)
    latency_ms: float = Field(ge=0)


class SupportingFusionState(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AGREEMENT = "AGREEMENT"
    FILLED = "FILLED"
    CONFLICT_ABSTAINED = "CONFLICT_ABSTAINED"
    UNGROUNDED = "UNGROUNDED"
    ROW_ASSOCIATION_REJECTED = "ROW_ASSOCIATION_REJECTED"


@dataclass(frozen=True)
class SupportingFusion:
    output: ExtractedPurchaseOrder | ExtractedGoodsReceipt
    outcomes: dict[str, SupportingFusionState]
    grounding: dict[str, str]


def route_supporting(
    output: ExtractedPurchaseOrder | ExtractedGoodsReceipt,
    document: DocumentText,
    role: DocumentRole,
    *,
    amount_tolerance: Decimal = Decimal("0.02"),
) -> SupportingRoute:
    if isinstance(output, ExtractedPurchaseOrder) != (role == DocumentRole.PURCHASE_ORDER):
        raise ValueError("supporting role does not match deterministic output")
    reasons: list[SupportingRouteReason] = []
    required_statuses = (
        [output.po_number.status, output.issue_date.status, output.currency.status]
        if isinstance(output, ExtractedPurchaseOrder)
        else [
            output.receipt_number.status,
            output.received_date.status,
            output.referenced_po_number.status,
        ]
    )
    if ExtractionStatus.MISSING in required_statuses:
        reasons.append(SupportingRouteReason.REQUIRED_FIELD_MISSING)
    if ExtractionStatus.AMBIGUOUS in required_statuses:
        reasons.append(SupportingRouteReason.REQUIRED_FIELD_AMBIGUOUS)
    if not output.line_items:
        reasons.append(SupportingRouteReason.NO_LINE_ITEMS)
    elif isinstance(output, ExtractedPurchaseOrder):
        if any(
            item.description.status != ExtractionStatus.EXTRACTED
            or item.ordered_quantity.status != ExtractionStatus.EXTRACTED
            or item.unit_price.status != ExtractionStatus.EXTRACTED
            or item.line_total.status != ExtractionStatus.EXTRACTED
            for item in output.line_items
        ):
            reasons.append(SupportingRouteReason.INCOMPLETE_LINE_ITEMS)
    elif any(
        item.description.status != ExtractionStatus.EXTRACTED
        or item.received_quantity.status != ExtractionStatus.EXTRACTED
        for item in output.line_items
    ):
        reasons.append(SupportingRouteReason.QUANTITY_ASSOCIATION_INCOMPLETE)
    if isinstance(output, ExtractedPurchaseOrder) and all(
        field.value is not None for field in (output.subtotal, output.tax, output.total)
    ):
        assert output.subtotal.value is not None
        assert output.tax.value is not None
        assert output.total.value is not None
        if abs(output.subtotal.value + output.tax.value - output.total.value) > amount_tolerance:
            reasons.append(SupportingRouteReason.TOTAL_CONFLICT)
    if document.used_ocr and any(
        status != ExtractionStatus.EXTRACTED for status in required_statuses
    ):
        reasons.append(SupportingRouteReason.OCR_REQUIRED_FIELD)
    # DELIVERY_NOTE intentionally shares goods-receipt semantics.
    return SupportingRoute(invoke_model=bool(reasons), reasons=list(dict.fromkeys(reasons)))


def _value_supported(name: str, value: str | date | Decimal, quote: str) -> bool:
    pieces = re.findall(r"[\w./+-]+", quote, flags=re.UNICODE)
    windows = [
        " ".join(pieces[start : start + size])
        for start in range(len(pieces))
        for size in range(1, min(5, len(pieces) - start) + 1)
    ]
    if isinstance(value, Decimal):
        return any(parse_money(piece) == value for piece in windows)
    if isinstance(value, date):
        return any(parse_invoice_date(piece) == value for piece in windows)
    if name == "currency":
        return any(normalize_currency(piece) == value for piece in windows)
    expected = normalize_identifier(str(value))
    return bool(expected) and any(normalize_identifier(piece) == expected for piece in windows)


def _normalization_name(name: str) -> str:
    if name in {"issue_date", "received_date"}:
        return "invoice_date"
    if name in {
        "subtotal",
        "tax",
        "total",
        "ordered_quantity",
        "received_quantity",
        "accepted_quantity",
        "rejected_quantity",
        "unit_price",
        "line_total",
    }:
        return "line_total"
    return name


_COLUMN_ALIASES: dict[str, set[str]] = {
    "description": {"description", "item", "product", "details"},
    "ordered_quantity": {"qty", "quantity", "ordered"},
    "unit_price": {"price", "rate"},
    "line_total": {"amount", "total"},
    "received_quantity": {"received", "delivered"},
    "accepted_quantity": {"accepted"},
    "rejected_quantity": {"rejected", "damaged"},
}


def _column_supported(name: str, field: ExtractedField[object], document: DocumentText) -> bool:
    if not field.evidence:
        return False
    span = field.evidence[0]
    center = (span.bbox.x0 + span.bbox.x1) / 2
    possible_headers: list[tuple[float, dict[str, float]]] = []
    for row in reconstruct_visual_rows(document):
        if row.page != span.page or row.y1 >= span.bbox.y0:
            continue
        anchors: dict[str, float] = {}
        for word in row.words:
            label = word.text.casefold().rstrip(".:")
            for column, aliases in _COLUMN_ALIASES.items():
                if label in aliases:
                    anchors[column] = (word.bbox.x0 + word.bbox.x1) / 2
        if "description" in anchors and name in anchors and len(anchors) >= 3:
            possible_headers.append((row.y1, anchors))
    if not possible_headers:
        return False
    anchors = max(possible_headers, key=lambda item: item[0])[1]
    ordered = sorted(anchors.items(), key=lambda item: item[1])
    index = next(index for index, item in enumerate(ordered) if item[0] == name)
    left = 0.0 if index == 0 else (ordered[index - 1][1] + ordered[index][1]) / 2
    right = 1.0 if index == len(ordered) - 1 else (
        ordered[index][1] + ordered[index + 1][1]
    ) / 2
    return left <= center <= right


def _ground_field(
    name: str, candidate: CandidateField, document: DocumentText
) -> tuple[ExtractedField[object] | None, str]:
    result = locate_supporting_quote(
        _normalization_name(name), candidate, document, fuzzy_threshold=100
    )
    if not result.grounded or result.normalized_value is None:
        return None, result.reason.value
    if not candidate.evidence_quote or not _value_supported(
        name, result.normalized_value, candidate.evidence_quote
    ):
        return None, GroundingReason.VALUE_NORMALIZATION_FAILED.value
    if name in {"subtotal", "tax", "total"}:
        label = {
            "subtotal": r"\bsub\s*total\b",
            "tax": r"\b(?:tax|gst|vat)\b",
            "total": r"\b(?:grand\s+total|amount\s+due|total)\b",
        }[name]
        if re.search(label, candidate.evidence_quote, re.I) is None:
            return None, GroundingReason.VALUE_NORMALIZATION_FAILED.value
        suffix = re.split(label, candidate.evidence_quote, maxsplit=1, flags=re.I)[-1]
        numbers = re.findall(r"[+-]?\d[\d,.]*", suffix)
        if not numbers or parse_money(numbers[0]) != result.normalized_value:
            return None, GroundingReason.VALUE_NORMALIZATION_FAILED.value
    proposed = ExtractedField[object](
        value=result.normalized_value,
        status=ExtractionStatus.EXTRACTED,
        evidence=list(result.evidence),
        rule_id="supporting.vlm.grounded.v1",
    )
    if name in {
        "ordered_quantity", "unit_price", "line_total", "received_quantity",
        "accepted_quantity", "rejected_quantity",
    } and not _column_supported(name, proposed, document):
        return None, GroundingReason.VALUE_NORMALIZATION_FAILED.value
    return (
        proposed,
        result.reason.value,
    )


def _fuse_field(
    path: str,
    deterministic: ExtractedField[object],
    candidate: CandidateField,
    document: DocumentText,
    outcomes: dict[str, SupportingFusionState],
    grounding: dict[str, str],
) -> ExtractedField[object]:
    if candidate.raw_value is None:
        outcomes[path] = SupportingFusionState.DETERMINISTIC
        return deterministic
    name = path.rsplit(".", 1)[-1]
    proposed, reason = _ground_field(name, candidate, document)
    grounding[path] = reason
    if proposed is None:
        outcomes[path] = SupportingFusionState.UNGROUNDED
        return deterministic
    if deterministic.status == ExtractionStatus.EXTRACTED:
        if deterministic.value == proposed.value:
            outcomes[path] = SupportingFusionState.AGREEMENT
            return deterministic
        outcomes[path] = SupportingFusionState.CONFLICT_ABSTAINED
        return ExtractedField[object](
            value=None,
            status=ExtractionStatus.AMBIGUOUS,
            evidence=[*deterministic.evidence, *proposed.evidence],
            rule_id="supporting.vlm.conflict.v1",
        )
    outcomes[path] = SupportingFusionState.FILLED
    return proposed


def _same_row(fields: Sequence[ExtractedField[object] | ExtractedField[str]]) -> bool:
    evidence = [field.evidence[0] for field in fields if field.evidence]
    if len(evidence) != len(fields) or len({item.page for item in evidence}) != 1:
        return False
    return max(item.bbox.y0 for item in evidence) <= min(item.bbox.y1 for item in evidence)


def fuse_supporting(
    deterministic: ExtractedPurchaseOrder | ExtractedGoodsReceipt,
    candidate: PurchaseOrderCandidate | GoodsReceiptCandidate | DeliveryNoteCandidate,
    document: DocumentText,
) -> SupportingFusion:
    if isinstance(deterministic, ExtractedPurchaseOrder) != isinstance(
        candidate, PurchaseOrderCandidate
    ):
        raise ValueError("candidate role does not match deterministic output")
    outcomes: dict[str, SupportingFusionState] = {}
    grounding: dict[str, str] = {}
    po = isinstance(deterministic, ExtractedPurchaseOrder)
    header_names = (
        ("po_number", "issue_date", "vendor", "buyer", "currency", "subtotal", "tax", "total")
        if po
        else ("receipt_number", "referenced_po_number", "received_date", "supplier")
    )
    line_names = (
        ("line_number", "description", "ordered_quantity", "unit_price", "line_total")
        if po
        else ("description", "received_quantity", "accepted_quantity", "rejected_quantity")
    )
    values: dict[str, object] = {}
    for name in header_names:
        values[name] = _fuse_field(
            name,
            getattr(deterministic, name),
            getattr(candidate, name),
            document,
            outcomes,
            grounding,
        )
    lines: list[ExtractedPurchaseOrderLine | ExtractedGoodsReceiptLine] = []
    for index, raw_line in enumerate(candidate.line_items):
        candidate_line = cast(PurchaseOrderLineCandidate | GoodsReceiptLineCandidate, raw_line)
        original = (
            deterministic.line_items[index] if index < len(deterministic.line_items) else None
        )
        proposed: dict[str, ExtractedField[object]] = {}
        for name in line_names:
            path = f"line_items.{index}.{name}"
            original_field = (
                getattr(original, name)
                if original is not None
                else ExtractedField[object](
                    value=None, status=ExtractionStatus.MISSING, evidence=[]
                )
            )
            proposed[name] = _fuse_field(
                path,
                original_field,
                getattr(candidate_line, name),
                document,
                outcomes,
                grounding,
            )
        candidate_row: list[ExtractedField[object]] = []
        for name in line_names:
            field = getattr(candidate_line, name)
            if field.raw_value is not None:
                grounded, _reason = _ground_field(name, field, document)
                if grounded is not None:
                    candidate_row.append(grounded)
        candidate_description, _reason = _ground_field(
            "description", candidate_line.description, document
        )
        original_description = original.description if original is not None else None
        association = (
            candidate_description is not None
            and len(candidate_row) >= 2
            and _same_row(candidate_row)
            and (
                original_description is None
                or not original_description.evidence
                or _same_row([original_description, candidate_description])
            )
        )
        if not association:
            # A model cannot associate a quantity with a line by list index alone.
            if original is not None:
                lines.append(original)
            for name in line_names:
                outcomes[f"line_items.{index}.{name}"] = (
                    SupportingFusionState.ROW_ASSOCIATION_REJECTED
                )
            continue
        line_type = ExtractedPurchaseOrderLine if po else ExtractedGoodsReceiptLine
        lines.append(line_type.model_validate(proposed))
    lines.extend(deterministic.line_items[len(candidate.line_items) :])
    values["line_items"] = lines
    output_type = ExtractedPurchaseOrder if po else ExtractedGoodsReceipt
    return SupportingFusion(output_type.model_validate(values), outcomes, grounding)
