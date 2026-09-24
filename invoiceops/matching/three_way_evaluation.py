import hashlib
import json
import platform
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.matching.three_way import match_invoice_three_way
from invoiceops.risk.evaluation import source_tree_fingerprint
from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    TextSource,
)
from invoiceops.schemas.matching import (
    MatchDecision,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    ReasonCode,
    ThreeWayMatchingPolicy,
)
from invoiceops.schemas.three_way import (
    ReceiptLineContextRead,
    ReceiptQuantityRead,
    ThreeWayContextSnapshot,
)

SCENARIO_SET_VERSION = "three-way-synthetic-v1"


class ThreeWayEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_count: int = Field(ge=25)
    expected_decision_accuracy: float = Field(ge=0, le=1)
    expected_reason_recall: float = Field(ge=0, le=1)
    straight_through_three_way_match_rate: float = Field(ge=0, le=1)
    needs_review_rate: float = Field(ge=0, le=1)
    false_auto_match_count: int = Field(ge=0)
    allocation_on_review_count: int = Field(ge=0)
    allocation_correctness_rate: float = Field(ge=0, le=1)
    cumulative_overbilling_detection_rate: float = Field(ge=0, le=1)
    idempotency_accuracy: float = Field(ge=0, le=1)
    serialized_overbilling_scenario_accuracy: float = Field(ge=0, le=1)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    policy_version: str
    scenario_set_version: str
    scenario_fingerprint: str
    source_tree_fingerprint: str
    python_version: str


@dataclass(frozen=True)
class Scenario:
    name: str
    received: Decimal
    invoice_quantity: Decimal
    prior: Decimal = Decimal("0")
    reversed_receipt: bool = False
    after_invoice: bool = False
    receipt_count: int = 1
    expected: MatchDecision = MatchDecision.MATCHED
    reason: ReasonCode | None = None


def scenarios() -> list[Scenario]:
    return [
        *[Scenario(f"fully-received-{i}", Decimal("10"), Decimal("10")) for i in range(3)],
        *[Scenario(f"partial-receipt-{i}", Decimal("6"), Decimal("6")) for i in range(3)],
        *[
            Scenario(f"multiple-receipts-{i}", Decimal("10"), Decimal("10"), receipt_count=2)
            for i in range(3)
        ],
        *[
            Scenario(f"cumulative-partial-{i}", Decimal("10"), Decimal("4"), prior=Decimal("6"))
            for i in range(3)
        ],
        *[Scenario(f"policy-boundary-{i}", Decimal("10"), Decimal("10.01")) for i in range(2)],
        *[
            Scenario(
                f"over-invoice-{i}",
                Decimal("8"),
                Decimal("9"),
                expected=MatchDecision.NEEDS_REVIEW,
                reason=ReasonCode.INVOICE_QUANTITY_EXCEEDS_RECEIVED,
            )
            for i in range(2)
        ],
        *[
            Scenario(
                f"cumulative-over-{i}",
                Decimal("10"),
                Decimal("5"),
                prior=Decimal("6"),
                expected=MatchDecision.NEEDS_REVIEW,
                reason=ReasonCode.CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED,
            )
            for i in range(2)
        ],
        Scenario(
            "over-receipt-0",
            Decimal("11"),
            Decimal("10"),
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.RECEIVED_QUANTITY_EXCEEDS_ORDERED,
        ),
        Scenario(
            "over-receipt-1",
            Decimal("12"),
            Decimal("10"),
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.RECEIVED_QUANTITY_EXCEEDS_ORDERED,
        ),
        Scenario(
            "reversed-0",
            Decimal("10"),
            Decimal("10"),
            reversed_receipt=True,
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.GOODS_RECEIPT_REVERSED,
        ),
        Scenario(
            "reversed-1",
            Decimal("10"),
            Decimal("10"),
            reversed_receipt=True,
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.GOODS_RECEIPT_REVERSED,
        ),
        Scenario(
            "post-invoice-0",
            Decimal("10"),
            Decimal("10"),
            after_invoice=True,
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.RECEIPT_AFTER_INVOICE,
        ),
        Scenario(
            "post-invoice-1",
            Decimal("10"),
            Decimal("10"),
            after_invoice=True,
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.RECEIPT_AFTER_INVOICE,
        ),
        Scenario(
            "missing-receipt-0",
            Decimal("0"),
            Decimal("10"),
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.NO_GOODS_RECEIPT,
        ),
        Scenario(
            "missing-receipt-1",
            Decimal("0"),
            Decimal("10"),
            expected=MatchDecision.NEEDS_REVIEW,
            reason=ReasonCode.NO_GOODS_RECEIPT,
        ),
    ]


def _field[T](value: T) -> ExtractedField[T]:
    evidence = EvidenceSpan(
        page=0,
        bbox=BoundingBox(x0=0, y0=0, x1=0.1, y1=0.1),
        text="synthetic",
        source=TextSource.EMBEDDED,
    )
    return ExtractedField(value=value, status=ExtractionStatus.EXTRACTED, evidence=[evidence])


def _inputs(scenario: Scenario) -> tuple[Invoice, PurchaseOrderRead, ThreeWayContextSnapshot]:
    po_id = uuid.uuid5(uuid.NAMESPACE_URL, f"invoiceops:3way:{scenario.name}:po")
    line_id = uuid.uuid5(uuid.NAMESPACE_URL, f"invoiceops:3way:{scenario.name}:line")
    po = PurchaseOrderRead(
        id=po_id,
        external_po_number=f"PO-{scenario.name}",
        vendor_name="Synthetic Vendor",
        currency="INR",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        lines=[
            PurchaseOrderLineRead(
                id=line_id,
                purchase_order_id=po_id,
                line_number="1",
                description="Synthetic Part",
                ordered_quantity=Decimal("10"),
                unit_price=Decimal("5"),
            )
        ],
    )
    total = scenario.invoice_quantity * Decimal("5")
    invoice = Invoice(
        invoice_number=_field(f"INV-{scenario.name}"),
        invoice_date=_field(date(2026, 1, 15)),
        currency=_field("INR"),
        subtotal=_field(total),
        tax=_field(Decimal("0")),
        total=_field(total),
        line_items=[
            InvoiceLine(
                description=_field("Synthetic Part"),
                quantity=_field(scenario.invoice_quantity),
                unit_price=_field(Decimal("5")),
                line_total=_field(total),
            )
        ],
    )
    active = []
    if scenario.received > 0 and not scenario.reversed_receipt:
        each = scenario.received / scenario.receipt_count
        active = [
            ReceiptQuantityRead(
                receipt_id=uuid.uuid5(
                    uuid.NAMESPACE_URL, f"invoiceops:3way:{scenario.name}:receipt:{index}"
                ),
                accepted_quantity=format(each, "f"),
                received_at=datetime(2026, 1, 16 if scenario.after_invoice else 14, tzinfo=UTC),
            )
            for index in range(scenario.receipt_count)
        ]
    context = ThreeWayContextSnapshot(
        purchase_order_id=po_id,
        policy_version="three-way-v1",
        lines=[
            ReceiptLineContextRead(
                purchase_order_line_id=line_id,
                ordered_quantity="10",
                active_receipts=active,
                reversed_receipts=[
                    ReceiptQuantityRead(
                        receipt_id=uuid.uuid4(),
                        accepted_quantity=format(scenario.received, "f"),
                        received_at=datetime(2026, 1, 14, tzinfo=UTC),
                    )
                ]
                if scenario.reversed_receipt
                else [],
                reversal_ids=[uuid.uuid4()] if scenario.reversed_receipt else [],
                effective_received_quantity=format(
                    scenario.received if active else Decimal("0"), "f"
                ),
                previously_allocated_quantity=format(scenario.prior, "f"),
                available_quantity=format(
                    (scenario.received if active else Decimal("0")) - scenario.prior, "f"
                ),
            )
        ],
    )
    return invoice, po, context


def run_evaluation() -> ThreeWayEvaluationReport:
    selected = scenarios()
    policy = ThreeWayMatchingPolicy(quantity_absolute_tolerance=Decimal("0.01"))
    correct = reasons = false_auto = allocation_on_review = matched = 0
    allocation_correct = cumulative_total = cumulative_detected = idempotent = 0
    latencies: list[float] = []
    for scenario in selected:
        invoice, po, context = _inputs(scenario)
        started = time.perf_counter()
        result, allocations = match_invoice_three_way(invoice, po, context, policy)
        latencies.append((time.perf_counter() - started) * 1000)
        correct += result.decision == scenario.expected
        reasons += scenario.reason is None or scenario.reason in result.reason_codes
        false_auto += (
            scenario.expected == MatchDecision.NEEDS_REVIEW
            and result.decision == MatchDecision.MATCHED
        )
        allocation_on_review += result.decision == MatchDecision.NEEDS_REVIEW and bool(allocations)
        matched += result.decision == MatchDecision.MATCHED
        allocation_correct += bool(allocations) == (result.decision == MatchDecision.MATCHED)
        if scenario.reason == ReasonCode.CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED:
            cumulative_total += 1
            cumulative_detected += scenario.reason in result.reason_codes
        repeated, repeated_allocations = match_invoice_three_way(invoice, po, context, policy)
        idempotent += (
            repeated.model_dump(mode="json") == result.model_dump(mode="json")
            and repeated_allocations == allocations
        )
    ordered = sorted(latencies)
    fingerprint = hashlib.sha256(
        json.dumps(
            [item.__dict__ for item in selected], sort_keys=True, default=str, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return ThreeWayEvaluationReport(
        scenario_count=len(selected),
        expected_decision_accuracy=correct / len(selected),
        expected_reason_recall=reasons / len(selected),
        straight_through_three_way_match_rate=matched / len(selected),
        needs_review_rate=(len(selected) - matched) / len(selected),
        false_auto_match_count=false_auto,
        allocation_on_review_count=allocation_on_review,
        allocation_correctness_rate=allocation_correct / len(selected),
        cumulative_overbilling_detection_rate=(
            cumulative_detected / cumulative_total if cumulative_total else 1
        ),
        idempotency_accuracy=idempotent / len(selected),
        serialized_overbilling_scenario_accuracy=(
            cumulative_detected / cumulative_total if cumulative_total else 1
        ),
        p50_latency_ms=round(ordered[len(ordered) // 2], 4),
        p95_latency_ms=round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 4),
        policy_version=policy.version,
        scenario_set_version=SCENARIO_SET_VERSION,
        scenario_fingerprint=fingerprint,
        source_tree_fingerprint=source_tree_fingerprint(),
        python_version=platform.python_version(),
    )


def write_report(output_dir: Path, report: ThreeWayEvaluationReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.joinpath("report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    output_dir.joinpath("report.md").write_text(
        "\n".join(
            [
                "# Three-way matching evaluation",
                "",
                "Synthetic/de-identified scenarios only; these are not production claims.",
                "",
                f"- Scenario count: {report.scenario_count}",
                f"- Expected decision accuracy: {report.expected_decision_accuracy:.4f}",
                f"- Expected reason recall: {report.expected_reason_recall:.4f}",
                "- Straight-through three-way match rate: "
                f"{report.straight_through_three_way_match_rate:.4f}",
                f"- Needs-review rate: {report.needs_review_rate:.4f}",
                f"- False auto-match count: {report.false_auto_match_count}",
                f"- Allocation-on-review count: {report.allocation_on_review_count}",
                f"- Allocation correctness rate: {report.allocation_correctness_rate:.4f}",
                "- Cumulative-overbilling detection rate: "
                f"{report.cumulative_overbilling_detection_rate:.4f}",
                f"- Idempotency accuracy: {report.idempotency_accuracy:.4f}",
                "- Serialized overbilling scenario accuracy: "
                f"{report.serialized_overbilling_scenario_accuracy:.4f}",
                f"- p50 latency: {report.p50_latency_ms:.4f} ms",
                f"- p95 latency: {report.p95_latency_ms:.4f} ms",
                f"- Scenario fingerprint: `{report.scenario_fingerprint}`",
                f"- Source-tree fingerprint: `{report.source_tree_fingerprint}`",
                "",
                "A match result, duplicate-risk disposition, human resolution and "
                "payment authorization remain separate decisions.",
                "The offline suite is sequential; PostgreSQL contention is tested in Compose.",
                "",
            ]
        ),
        encoding="utf-8",
    )
