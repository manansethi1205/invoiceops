import hashlib
import json
import math
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.matching.engine import match_invoice
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
    MatchingPolicy,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    ReasonCode,
)


class MatchingEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_count: int = Field(gt=0)
    expected_decision_accuracy: float = Field(ge=0, le=1)
    straight_through_match_rate: float = Field(ge=0, le=1)
    needs_review_rate: float = Field(ge=0, le=1)
    false_auto_match_count: int = Field(ge=0)
    reason_code_accuracy: float = Field(ge=0, le=1)
    p50_match_latency_ms: float = Field(ge=0)
    p95_match_latency_ms: float = Field(ge=0)
    policy_version: str
    scenario_set_version: str
    evaluation_timestamp: datetime
    python_version: str
    git_revision: str
    policy_hash: str


@dataclass(frozen=True)
class MatchingScenario:
    name: str
    invoice: Invoice
    purchase_order: PurchaseOrderRead
    expected_decision: MatchDecision
    required_reason_codes: frozenset[ReasonCode] = frozenset()


def _field[T](value: T) -> ExtractedField[T]:
    return ExtractedField[T](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=[
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2),
                text="synthetic-evaluation",
                source=TextSource.EMBEDDED,
            )
        ],
        rule_id="synthetic.evaluation",
    )


def _line(description: str, quantity: str, unit_price: str, total: str) -> InvoiceLine:
    return InvoiceLine(
        description=_field(description),
        quantity=_field(Decimal(quantity)),
        unit_price=_field(Decimal(unit_price)),
        line_total=_field(Decimal(total)),
    )


def _invoice(
    lines: list[InvoiceLine],
    *,
    currency: str = "INR",
    subtotal: str,
    tax: str = "0",
    total: str | None = None,
) -> Invoice:
    subtotal_value = Decimal(subtotal)
    tax_value = Decimal(tax)
    return Invoice(
        invoice_number=_field("EVAL-001"),
        invoice_date=_field(date(2026, 9, 21)),
        currency=_field(currency),
        subtotal=_field(subtotal_value),
        tax=_field(tax_value),
        total=_field(Decimal(total) if total is not None else subtotal_value + tax_value),
        line_items=lines,
    )


def _po(
    lines: list[tuple[str, str, str, str]], *, currency: str = "INR", suffix: str
) -> PurchaseOrderRead:
    po_id = uuid.uuid5(uuid.NAMESPACE_URL, f"invoiceops:matching-eval:{suffix}")
    return PurchaseOrderRead(
        id=po_id,
        external_po_number=f"PO-{suffix}",
        vendor_name="Synthetic Evaluation Vendor",
        currency=currency,
        created_at=datetime(2026, 9, 21, tzinfo=UTC),
        lines=[
            PurchaseOrderLineRead(
                id=uuid.uuid5(po_id, line_number),
                purchase_order_id=po_id,
                line_number=line_number,
                description=description,
                ordered_quantity=Decimal(quantity),
                unit_price=Decimal(unit_price),
            )
            for line_number, description, quantity, unit_price in lines
        ],
    )


def synthetic_matching_scenarios() -> list[MatchingScenario]:
    clean_po_lines = [("1", "Industrial Filter", "2", "500"), ("2", "Bracket", "4", "50")]
    clean_lines = [
        _line("Industrial Filter", "2", "500", "1000"),
        _line("Bracket", "4", "50", "200"),
    ]
    scenarios = [
        MatchingScenario(
            "clean-exact",
            _invoice(clean_lines, subtotal="1200"),
            _po(clean_po_lines, suffix="C1"),
            MatchDecision.MATCHED,
        ),
        MatchingScenario(
            "clean-reordered",
            _invoice(list(reversed(clean_lines)), subtotal="1200"),
            _po(clean_po_lines, suffix="C2"),
            MatchDecision.MATCHED,
        ),
        MatchingScenario(
            "clean-punctuation",
            _invoice([_line("Industrial—Filter", "2", "500", "1000")], subtotal="1000"),
            _po([("1", "Industrial Filter", "2", "500")], suffix="C3"),
            MatchDecision.MATCHED,
        ),
        MatchingScenario(
            "clean-price-boundary",
            _invoice([_line("Precision Part", "0.001", "101", "0.101")], subtotal="0.101"),
            _po([("1", "Precision Part", "0.001", "100")], suffix="C4"),
            MatchDecision.MATCHED,
        ),
        MatchingScenario(
            "clean-zero-price",
            _invoice([_line("Free Sample", "1", "0", "0")], subtotal="0"),
            _po([("1", "Free Sample", "1", "0")], suffix="C5"),
            MatchDecision.MATCHED,
        ),
    ]
    for index, price in enumerate(("102", "110", "150"), start=1):
        total = Decimal("0.001") * Decimal(price)
        scenarios.append(
            MatchingScenario(
                f"price-{index}",
                _invoice(
                    [_line("Precision Part", "0.001", price, str(total))], subtotal=str(total)
                ),
                _po([("1", "Precision Part", "0.001", "100")], suffix=f"P{index}"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.UNIT_PRICE_MISMATCH}),
            )
        )
    for index, quantity in enumerate(("2", "3"), start=1):
        total = Decimal(quantity) * Decimal("0.01")
        scenarios.append(
            MatchingScenario(
                f"quantity-{index}",
                _invoice([_line("Washer", quantity, "0.01", str(total))], subtotal=str(total)),
                _po([("1", "Washer", "1", "0.01")], suffix=f"Q{index}"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.QUANTITY_MISMATCH}),
            )
        )
    for index, currency in enumerate(("USD", "EUR"), start=1):
        scenarios.append(
            MatchingScenario(
                f"currency-{index}",
                _invoice([_line("Service", "1", "10", "10")], currency=currency, subtotal="10"),
                _po([("1", "Service", "1", "10")], suffix=f"U{index}"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.CURRENCY_MISMATCH}),
            )
        )
    for index in range(1, 3):
        scenarios.append(
            MatchingScenario(
                f"ambiguous-{index}",
                _invoice([_line("Blue Widget Premium", "1", "10", "10")], subtotal="10"),
                _po(
                    [
                        ("1", "Blue Widget Premium Pro", "1", "10"),
                        ("2", "Blue Widget Premium Plus", "1", "10"),
                    ],
                    suffix=f"A{index}",
                ),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.DESCRIPTION_AMBIGUOUS}),
            )
        )
    scenarios.extend(
        [
            MatchingScenario(
                "arithmetic-line",
                _invoice([_line("Service", "2", "10", "21")], subtotal="21"),
                _po([("1", "Service", "2", "10")], suffix="R1"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.INVOICE_LINE_ARITHMETIC_MISMATCH}),
            ),
            MatchingScenario(
                "arithmetic-total",
                _invoice([_line("Service", "1", "10", "10")], subtotal="10", tax="2", total="13"),
                _po([("1", "Service", "1", "10")], suffix="R2"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.INVOICE_TOTAL_MISMATCH}),
            ),
            MatchingScenario(
                "extra-line",
                _invoice(
                    [_line("Service", "1", "10", "10"), _line("Extra", "1", "1", "1")],
                    subtotal="11",
                ),
                _po([("1", "Service", "1", "10")], suffix="E1"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.EXTRA_INVOICE_LINE}),
            ),
            MatchingScenario(
                "missing-line",
                _invoice([_line("Service", "1", "10", "10")], subtotal="10"),
                _po([("1", "Service", "1", "10"), ("2", "Missing", "1", "1")], suffix="E2"),
                MatchDecision.NEEDS_REVIEW,
                frozenset({ReasonCode.PO_LINE_UNMATCHED}),
            ),
        ]
    )
    return scenarios


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def run_matching_evaluation(
    scenarios: list[MatchingScenario] | None = None,
    policy: MatchingPolicy | None = None,
) -> MatchingEvaluationReport:
    selected = scenarios or synthetic_matching_scenarios()
    effective_policy = policy or MatchingPolicy()
    policy_json = json.dumps(
        effective_policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    decisions_correct = 0
    matched = 0
    false_auto_matches = 0
    reason_sets_correct = 0
    review_scenarios = 0
    latencies: list[float] = []
    for scenario in selected:
        started = time.perf_counter()
        result = match_invoice(scenario.invoice, scenario.purchase_order, effective_policy)
        latencies.append((time.perf_counter() - started) * 1000)
        decisions_correct += result.decision == scenario.expected_decision
        matched += result.decision == MatchDecision.MATCHED
        false_auto_matches += (
            result.decision == MatchDecision.MATCHED
            and scenario.expected_decision == MatchDecision.NEEDS_REVIEW
        )
        if scenario.expected_decision == MatchDecision.NEEDS_REVIEW:
            review_scenarios += 1
            reason_sets_correct += scenario.required_reason_codes.issubset(result.reason_codes)
    count = len(selected)
    return MatchingEvaluationReport(
        scenario_count=count,
        expected_decision_accuracy=decisions_correct / count,
        straight_through_match_rate=matched / count,
        needs_review_rate=(count - matched) / count,
        false_auto_match_count=false_auto_matches,
        reason_code_accuracy=(reason_sets_correct / review_scenarios if review_scenarios else 1.0),
        p50_match_latency_ms=round(_percentile(latencies, 0.50), 4),
        p95_match_latency_ms=round(_percentile(latencies, 0.95), 4),
        policy_version=effective_policy.version,
        scenario_set_version="matching-synthetic-v1",
        evaluation_timestamp=datetime.now(UTC),
        python_version=platform.python_version(),
        git_revision=_git_revision(),
        policy_hash=hashlib.sha256(policy_json.encode()).hexdigest(),
    )


def _git_revision() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def render_matching_report(report: MatchingEvaluationReport) -> str:
    return "\n".join(
        [
            "# Deterministic two-way matching evaluation",
            "",
            "Synthetic/de-identified scenarios only; these results are not production claims.",
            "",
            f"- Scenario count: {report.scenario_count}",
            f"- Policy version: `{report.policy_version}`",
            f"- Policy hash: `{report.policy_hash}`",
            f"- Scenario set: `{report.scenario_set_version}`",
            f"- Git revision: `{report.git_revision}`",
            f"- Python: `{report.python_version}`",
            f"- Evaluated: `{report.evaluation_timestamp.isoformat()}`",
            f"- Expected decision accuracy: {report.expected_decision_accuracy:.4f}",
            f"- Straight-through match rate: {report.straight_through_match_rate:.4f}",
            f"- Needs-review rate: {report.needs_review_rate:.4f}",
            f"- False auto-match count: {report.false_auto_match_count}",
            f"- Required reason-code accuracy: {report.reason_code_accuracy:.4f}",
            f"- p50 match latency: {report.p50_match_latency_ms:.4f} ms",
            f"- p95 match latency: {report.p95_match_latency_ms:.4f} ms",
            "",
            "Reason-code accuracy is the fraction of review scenarios containing every required "
            "ground-truth reason code; additional distinct downstream exceptions are allowed.",
            "",
        ]
    )


def write_matching_report(path: Path, report: MatchingEvaluationReport) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (path / "report.md").write_text(render_matching_report(report), encoding="utf-8")
