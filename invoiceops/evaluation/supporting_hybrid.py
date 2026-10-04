"""Frozen synthetic/replay comparison; never opens storage or writes canonical records."""

import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.extraction.hybrid.schemas import CandidateField, VisionUsage
from invoiceops.extraction.supporting import (
    extract_goods_receipt,
    extract_purchase_order,
    extract_purchase_order_v1,
)
from invoiceops.extraction.supporting_hybrid import (
    GoodsReceiptCandidate,
    PurchaseOrderCandidate,
    SupportingFusionState,
    SupportingResponse,
    fuse_supporting,
    route_supporting,
)
from invoiceops.schemas.cases import DocumentRole, ExtractedGoodsReceipt, ExtractedPurchaseOrder
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)

HEADER_NAMES = {
    DocumentRole.PURCHASE_ORDER: ("po_number", "issue_date", "currency"),
    DocumentRole.GOODS_RECEIPT: ("receipt_number", "received_date", "referenced_po_number"),
    DocumentRole.DELIVERY_NOTE: ("receipt_number", "received_date", "referenced_po_number"),
}


class RoleMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: int
    header_exact: dict[str, float]
    header_exact_counts: dict[str, int]
    line_true_positive: int
    line_predicted: int
    line_actual: int
    line_item_precision: float = Field(ge=0, le=1)
    line_item_recall: float = Field(ge=0, le=1)
    line_item_f1: float = Field(ge=0, le=1)
    schema_validity_rate: float = Field(ge=0, le=1)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    estimated_model_cost_per_document: Decimal | None


class SupportingReplayReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_id: str
    dataset_fingerprint: str
    example_count: int
    old_deterministic: dict[str, RoleMetrics]
    deterministic: dict[str, RoleMetrics]
    hybrid_replay: dict[str, RoleMetrics]
    routed_document_rate: float
    routed_documents: int
    grounded_acceptance_rate: float
    grounded_acceptances: int
    proposed_candidates: int
    abstention_rate: float
    abstained_documents: int
    conflict_rate: float
    conflicting_candidates: int
    grounded_candidates: int
    confirmation_rate: float | None
    confirmation_required_rate: float
    false_canonical_record_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    estimated_model_cost_per_document: Decimal | None
    latency_source: str
    usage_source: str
    limitations: list[str]


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    role: DocumentRole
    document: DocumentText
    truth: dict[str, str]
    truth_lines: tuple[tuple[str, ...], ...]
    response: SupportingResponse | None


def _document(rows: list[list[tuple[str, float]]]) -> DocumentText:
    words = [
        WordToken(
            text=text,
            page=0,
            bbox=BoundingBox(
                x0=x,
                y0=0.05 + row_index * 0.06,
                x1=min(1, x + max(0.04, len(text) * 0.008)),
                y1=0.08 + row_index * 0.06,
            ),
            block_number=0,
            line_number=row_index,
            word_number=word_index,
            source=TextSource.EMBEDDED,
        )
        for row_index, row in enumerate(rows)
        for word_index, (text, x) in enumerate(row)
    ]
    return DocumentText(
        pages=[
            PageText(
                page=0,
                width=1000,
                height=1000,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=words,
            )
        ],
        used_ocr=False,
    )


def _candidate(value: str | None = None) -> CandidateField:
    return CandidateField(
        raw_value=value,
        page=0 if value else None,
        evidence_quote=value,
        confidence=0.8 if value else None,
    )


def _po_candidate(number: str) -> PurchaseOrderCandidate:
    empty = _candidate()
    return PurchaseOrderCandidate(
        po_number=_candidate(number),
        issue_date=empty,
        vendor=empty,
        buyer=empty,
        currency=empty,
        subtotal=empty,
        tax=empty,
        total=empty,
        line_items=[],
    )


def _receipt_candidate(number: str) -> GoodsReceiptCandidate:
    empty = _candidate()
    return GoodsReceiptCandidate(
        receipt_number=_candidate(number),
        referenced_po_number=empty,
        received_date=empty,
        supplier=empty,
        line_items=[],
    )


def frozen_cases() -> tuple[ReplayCase, ...]:
    po_header = [
        [("Order", 0.05), ("Date:", 0.15), ("30/09/2026", 0.3)],
        [("Currency:", 0.05), ("INR", 0.3)],
        [
            ("Line", 0.01),
            ("Description", 0.1),
            ("Qty", 0.5),
            ("Unit", 0.62),
            ("Price", 0.68),
            ("Amount", 0.85),
        ],
        [("1", 0.01), ("Widgets", 0.1), ("2", 0.51), ("10.00", 0.7), ("20.00", 0.86)],
    ]
    receipt_header = [
        [("Delivery", 0.05), ("Date:", 0.15), ("01/10/2026", 0.3)],
        [("PO", 0.05), ("No:", 0.14), ("PO-100", 0.3)],
        [("Description", 0.05), ("Received", 0.5), ("Accepted", 0.68), ("Rejected", 0.84)],
        [("Widgets", 0.05), ("2", 0.5), ("2", 0.68), ("0", 0.84)],
    ]
    po_truth = {"issue_date": "2026-09-30", "currency": "INR"}
    receipt_truth = {"received_date": "2026-10-01", "referenced_po_number": "PO-100"}
    return (
        ReplayCase(
            "po-complete",
            DocumentRole.PURCHASE_ORDER,
            _document([[("PO", 0.05), ("No:", 0.14), ("PO-100", 0.3)], *po_header]),
            {**po_truth, "po_number": "PO-100"},
            (("Widgets", "2", "10", "20"),),
            None,
        ),
        ReplayCase(
            "po-missing-number",
            DocumentRole.PURCHASE_ORDER,
            _document([[("Reference", 0.05), ("ABC-200", 0.3)], *po_header]),
            {**po_truth, "po_number": "ABC-200"},
            (("Widgets", "2", "10", "20"),),
            SupportingResponse(
                candidate=_po_candidate("ABC-200"),
                usage=VisionUsage(input_tokens=100, output_tokens=20),
                latency_ms=10,
            ),
        ),
        ReplayCase(
            "po-conflict",
            DocumentRole.PURCHASE_ORDER,
            _document(
                [
                    [("PO", 0.05), ("No:", 0.14), ("PO-300", 0.3)],
                    [("Reference", 0.05), ("ABC-301", 0.3)],
                    *po_header[:2],
                ]
            ),
            {**po_truth, "po_number": "PO-300"},
            (),
            SupportingResponse(
                candidate=_po_candidate("ABC-301"),
                usage=VisionUsage(input_tokens=100, output_tokens=20),
                latency_ms=10,
            ),
        ),
        ReplayCase(
            "receipt-complete",
            DocumentRole.GOODS_RECEIPT,
            _document([[("Goods", 0.05), ("Receipt", 0.13), ("GR-1", 0.3)], *receipt_header]),
            {**receipt_truth, "receipt_number": "GR-1"},
            (("Widgets", "2", "2", "0"),),
            None,
        ),
        ReplayCase(
            "receipt-missing-number",
            DocumentRole.GOODS_RECEIPT,
            _document([[("Reference", 0.05), ("RG-2", 0.3)], *receipt_header]),
            {**receipt_truth, "receipt_number": "RG-2"},
            (("Widgets", "2", "2", "0"),),
            SupportingResponse(
                candidate=_receipt_candidate("RG-2"),
                usage=VisionUsage(input_tokens=80, output_tokens=16),
                latency_ms=8,
            ),
        ),
        ReplayCase(
            "delivery-complete",
            DocumentRole.DELIVERY_NOTE,
            _document([[("Delivery", 0.05), ("Note", 0.13), ("DN-1", 0.3)], *receipt_header]),
            {**receipt_truth, "receipt_number": "DN-1"},
            (("Widgets", "2", "2", "0"),),
            None,
        ),
    )


def _lines(output: ExtractedPurchaseOrder | ExtractedGoodsReceipt) -> Counter[tuple[str, ...]]:
    result: Counter[tuple[str, ...]] = Counter()
    if isinstance(output, ExtractedPurchaseOrder):
        rows = [
            (line.description, line.ordered_quantity, line.unit_price, line.line_total)
            for line in output.line_items
        ]
    else:
        rows = [
            (
                line.description,
                line.received_quantity,
                line.accepted_quantity,
                line.rejected_quantity,
            )
            for line in output.line_items
        ]
    for fields in rows:
        if all(field.status == ExtractionStatus.EXTRACTED for field in fields):
            result[
                tuple(
                    format(Decimal(str(field.value)).normalize(), "f")
                    if isinstance(field.value, Decimal)
                    else str(field.value)
                    for field in fields
                )
            ] += 1
    return result


def _score_role(
    cases: list[tuple[ReplayCase, ExtractedPurchaseOrder | ExtractedGoodsReceipt]],
    latencies: list[float],
    estimated_cost: Decimal | None,
) -> RoleMetrics:
    fields = HEADER_NAMES[cases[0][0].role]
    counts = {
        name: sum(
            str(getattr(output, name).value) == example.truth[name] for example, output in cases
        )
        for name in fields
    }
    exact = {name: count / len(cases) for name, count in counts.items()}
    true_positive = predicted = actual = 0
    for example, output in cases:
        prediction = _lines(output)
        truth = Counter(example.truth_lines)
        true_positive += sum((prediction & truth).values())
        predicted += sum(prediction.values())
        actual += sum(truth.values())
    precision = true_positive / predicted if predicted else 0.0
    recall = true_positive / actual if actual else 0.0
    return RoleMetrics(
        documents=len(cases),
        header_exact=exact,
        header_exact_counts=counts,
        line_true_positive=true_positive,
        line_predicted=predicted,
        line_actual=actual,
        line_item_precision=precision,
        line_item_recall=recall,
        line_item_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        schema_validity_rate=1.0,
        p50_latency_ms=median(latencies),
        p95_latency_ms=_percentile(latencies, 0.95),
        estimated_model_cost_per_document=estimated_cost,
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def run_supporting_replay_evaluation(
    cases: tuple[ReplayCase, ...] | None = None,
    *,
    dataset_id: str = "supporting-synthetic-replay-v1",
    input_cost_per_million: Decimal | None = None,
    output_cost_per_million: Decimal | None = None,
) -> SupportingReplayReport:
    if (input_cost_per_million is None) != (output_cost_per_million is None):
        raise ValueError("both token prices are required")
    if any(
        rate is not None and rate < 0 for rate in (input_cost_per_million, output_cost_per_million)
    ):
        raise ValueError("token prices must be nonnegative")
    examples = cases if cases is not None else frozen_cases()
    if not examples:
        raise ValueError("supporting replay requires examples")
    fingerprint = hashlib.sha256(
        json.dumps(
            [
                {
                    "id": item.case_id,
                    "role": item.role.value,
                    "document": item.document.model_dump(mode="json"),
                    "truth": item.truth,
                    "truth_lines": item.truth_lines,
                    "response": item.response.model_dump(mode="json") if item.response else None,
                }
                for item in examples
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    baseline_by_role: dict[
        str, list[tuple[ReplayCase, ExtractedPurchaseOrder | ExtractedGoodsReceipt]]
    ] = {}
    old_by_role: dict[
        str, list[tuple[ReplayCase, ExtractedPurchaseOrder | ExtractedGoodsReceipt]]
    ] = {}
    hybrid_by_role: dict[
        str, list[tuple[ReplayCase, ExtractedPurchaseOrder | ExtractedGoodsReceipt]]
    ] = {}
    routed = accepted = proposed = abstained = conflicts = grounded = 0
    input_tokens = output_tokens = 0
    durations: list[float] = []
    baseline_durations: dict[str, list[float]] = {}
    old_durations: dict[str, list[float]] = {}
    hybrid_durations: dict[str, list[float]] = {}
    role_usage: dict[str, tuple[int, int]] = {}
    for example in examples:
        old_started = time.perf_counter()
        old_output = (
            extract_purchase_order_v1(example.document)
            if example.role == DocumentRole.PURCHASE_ORDER
            else extract_goods_receipt(example.document)
        )
        old_elapsed = (time.perf_counter() - old_started) * 1000
        started = time.perf_counter()
        baseline = (
            extract_purchase_order(example.document)
            if example.role == DocumentRole.PURCHASE_ORDER
            else extract_goods_receipt(example.document)
        )
        baseline_elapsed = (time.perf_counter() - started) * 1000
        route = route_supporting(baseline, example.document, example.role)
        hybrid = baseline
        if route.invoke_model:
            routed += 1
            if example.response is not None:
                fused = fuse_supporting(baseline, example.response.candidate, example.document)
                hybrid = fused.output
                proposed += len(fused.grounding)
                grounded += sum(code == "GROUNDED_EXACT" for code in fused.grounding.values())
                accepted += sum(
                    state in {SupportingFusionState.FILLED, SupportingFusionState.AGREEMENT}
                    for state in fused.outcomes.values()
                )
                conflicts += sum(
                    state == SupportingFusionState.CONFLICT_ABSTAINED
                    for state in fused.outcomes.values()
                )
                if not any(
                    state == SupportingFusionState.FILLED for state in fused.outcomes.values()
                ):
                    abstained += 1
                input_tokens += example.response.usage.input_tokens or 0
                output_tokens += example.response.usage.output_tokens or 0
                old_input, old_output_tokens = role_usage.get(example.role.value, (0, 0))
                role_usage[example.role.value] = (
                    old_input + (example.response.usage.input_tokens or 0),
                    old_output_tokens + (example.response.usage.output_tokens or 0),
                )
            else:
                abstained += 1
        hybrid_elapsed = (time.perf_counter() - started) * 1000 + (
            example.response.latency_ms if route.invoke_model and example.response else 0
        )
        durations.append(hybrid_elapsed)
        baseline_durations.setdefault(example.role.value, []).append(baseline_elapsed)
        old_durations.setdefault(example.role.value, []).append(old_elapsed)
        old_by_role.setdefault(example.role.value, []).append((example, old_output))
        hybrid_durations.setdefault(example.role.value, []).append(hybrid_elapsed)
        baseline_by_role.setdefault(example.role.value, []).append((example, baseline))
        hybrid_by_role.setdefault(example.role.value, []).append((example, hybrid))
    estimated_cost = None
    if input_cost_per_million is not None and output_cost_per_million is not None:
        estimated_cost = (
            Decimal(input_tokens) * input_cost_per_million
            + Decimal(output_tokens) * output_cost_per_million
        ) / Decimal(1_000_000 * len(examples))
    role_cost: dict[str, Decimal | None] = {}
    for role, rows in baseline_by_role.items():
        if input_cost_per_million is None or output_cost_per_million is None:
            role_cost[role] = None
        else:
            role_input, role_output = role_usage.get(role, (0, 0))
            role_cost[role] = (
                Decimal(role_input) * input_cost_per_million
                + Decimal(role_output) * output_cost_per_million
            ) / Decimal(1_000_000 * len(rows))
    return SupportingReplayReport(
        dataset_id=dataset_id,
        dataset_fingerprint=fingerprint,
        example_count=len(examples),
        old_deterministic={
            key: _score_role(value, old_durations[key], Decimal(0))
            for key, value in old_by_role.items()
        },
        deterministic={
            key: _score_role(value, baseline_durations[key], Decimal(0))
            for key, value in baseline_by_role.items()
        },
        hybrid_replay={
            key: _score_role(value, hybrid_durations[key], role_cost[key])
            for key, value in hybrid_by_role.items()
        },
        routed_document_rate=routed / len(examples),
        routed_documents=routed,
        grounded_acceptance_rate=accepted / proposed if proposed else 0.0,
        grounded_acceptances=accepted,
        proposed_candidates=proposed,
        abstention_rate=abstained / routed if routed else 0.0,
        abstained_documents=abstained,
        conflict_rate=conflicts / grounded if grounded else 0.0,
        conflicting_candidates=conflicts,
        grounded_candidates=grounded,
        confirmation_rate=None,
        confirmation_required_rate=1.0,
        false_canonical_record_count=0,
        p50_latency_ms=median(durations),
        p95_latency_ms=_percentile(durations, 0.95),
        estimated_model_cost_per_document=estimated_cost,
        latency_source="local parser measured; replay provider milliseconds simulated",
        usage_source="synthetic replay; no live provider or human confirmation",
        limitations=[
            f"{len(examples)} synthetic examples; not a production accuracy estimate.",
            "Old 0.1.0 PO line reconstruction may include the printed line number.",
            "No canonical records are written; actual confirmation rate is unmeasured.",
            "Replay token counts and provider latency are synthetic; cost needs explicit rates.",
        ],
    )
