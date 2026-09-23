import math
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.risk.engine import assess_duplicate_risk
from invoiceops.schemas.risk import (
    DuplicateRiskPolicy,
    RiskDisposition,
    RiskFeatureSnapshot,
    RiskSignalCode,
)

SCENARIO_SET_VERSION = "duplicate-risk-synthetic-v1"
DUPLICATE_CODES = frozenset(
    {
        RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE,
        RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER,
        RiskSignalCode.SAME_PO_INVOICE_REPLAY,
        RiskSignalCode.NEAR_DUPLICATE,
    }
)


class DuplicateRiskEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_count: int = Field(ge=25)
    expected_disposition_accuracy: float = Field(ge=0, le=1)
    duplicate_signal_precision: float = Field(ge=0, le=1)
    duplicate_signal_recall: float = Field(ge=0, le=1)
    known_duplicate_false_clear_count: int = Field(ge=0)
    clean_invoice_false_review_count: int = Field(ge=0)
    incomplete_assessment_accuracy: float = Field(ge=0, le=1)
    duplicate_assessment_count: int = Field(ge=0)
    p50_risk_latency_ms: float = Field(ge=0)
    p95_risk_latency_ms: float = Field(ge=0)
    policy_version: str
    scenario_set_version: str
    source_revision: str
    evaluated_at: datetime
    python_version: str


@dataclass(frozen=True)
class DuplicateRiskScenario:
    name: str
    current: RiskFeatureSnapshot
    historical: tuple[RiskFeatureSnapshot, ...]
    expected_disposition: RiskDisposition
    expected_signals: frozenset[RiskSignalCode]


def _feature(
    scenario: str,
    role: str,
    *,
    vendor: str | None = "synthetic vendor",
    number: str | None = "invoice202600001",
    issued: date | None = date(2026, 9, 1),
    currency: str | None = "INR",
    total: str | None = "100.00",
    po_key: str | None = None,
) -> RiskFeatureSnapshot:
    missing = tuple(
        name
        for name, value in (
            ("normalized_vendor", vendor),
            ("normalized_invoice_number", number),
            ("invoice_date", issued),
            ("currency", currency),
            ("total", total),
        )
        if value is None
    )
    namespace = f"invoiceops:risk-eval:{scenario}:{role}"
    return RiskFeatureSnapshot(
        normalized_vendor=vendor,
        normalized_invoice_number=number,
        invoice_date=issued,
        currency=currency,
        total=total,
        purchase_order_id=uuid.uuid5(uuid.NAMESPACE_URL, po_key or f"{namespace}:po"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:document"),
        extraction_run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:extraction"),
        match_run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:match"),
        missing_fields=missing,
    )


def synthetic_duplicate_risk_scenarios() -> list[DuplicateRiskScenario]:
    scenarios: list[DuplicateRiskScenario] = []
    exact_codes = frozenset({RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE})
    for name in ("reexport", "rescan", "recompress", "rename", "reformat"):
        scenarios.append(
            DuplicateRiskScenario(
                f"exact-{name}",
                _feature(name, "current"),
                (_feature(name, "prior"),),
                RiskDisposition.NEEDS_REVIEW,
                exact_codes,
            )
        )

    reused_variants: tuple[tuple[str, dict[str, object]], ...] = (
        ("amount", {"total": "150.00"}),
        ("currency", {"currency": "USD"}),
        ("late-date", {"issued": date(2026, 10, 1)}),
        ("earlier-date", {"issued": date(2026, 8, 1)}),
    )
    for name, changes in reused_variants:
        scenarios.append(
            DuplicateRiskScenario(
                f"reused-{name}",
                _feature(name, "current", **cast(dict[str, Any], changes)),
                (_feature(name, "prior"),),
                RiskDisposition.NEEDS_REVIEW,
                frozenset({RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER}),
            )
        )

    for index in range(4):
        po_key = f"shared-po-{index}"
        scenarios.append(
            DuplicateRiskScenario(
                f"po-replay-{index}",
                _feature(
                    f"po-{index}", "current", total="200.00", po_key=po_key
                ),
                (_feature(f"po-{index}", "prior", po_key=po_key),),
                RiskDisposition.NEEDS_REVIEW,
                frozenset(
                    {
                        RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER,
                        RiskSignalCode.SAME_PO_INVOICE_REPLAY,
                    }
                ),
            )
        )

    for index, days in enumerate((0, 1, 6, 7)):
        scenarios.append(
            DuplicateRiskScenario(
                f"near-{index}",
                _feature(
                    f"near-{index}",
                    "current",
                    number="invoice202600002",
                    issued=date(2026, 9, 1) + timedelta(days=days),
                    total="100.02",
                ),
                (_feature(f"near-{index}", "prior"),),
                RiskDisposition.NEEDS_REVIEW,
                frozenset({RiskSignalCode.NEAR_DUPLICATE}),
            )
        )

    for index in range(3):
        scenarios.append(
            DuplicateRiskScenario(
                f"cross-vendor-{index}",
                _feature(f"vendor-{index}", "current", vendor=f"other vendor {index}"),
                (_feature(f"vendor-{index}", "prior"),),
                RiskDisposition.CLEAR,
                frozenset(),
            )
        )

    incomplete_variants: tuple[tuple[str, dict[str, object]], ...] = (
        ("vendor", {"vendor": None}),
        ("number", {"number": None}),
        ("financials", {"currency": None, "total": None}),
    )
    for field_name, changes in incomplete_variants:
        scenarios.append(
            DuplicateRiskScenario(
                f"incomplete-{field_name}",
                _feature(field_name, "current", **cast(dict[str, Any], changes)),
                (),
                RiskDisposition.NEEDS_REVIEW,
                frozenset({RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE}),
            )
        )

    for index in range(2):
        scenarios.append(
            DuplicateRiskScenario(
                f"clean-{index}",
                _feature(
                    f"clean-{index}",
                    "current",
                    number=f"clean00000000{index}",
                    total=f"{300 + index}.00",
                ),
                (_feature(f"clean-{index}", "prior"),),
                RiskDisposition.CLEAR,
                frozenset(),
            )
        )
    return scenarios


def run_duplicate_risk_evaluation(
    scenarios: list[DuplicateRiskScenario] | None = None,
    policy: DuplicateRiskPolicy | None = None,
) -> DuplicateRiskEvaluationReport:
    selected = scenarios or synthetic_duplicate_risk_scenarios()
    effective_policy = policy or DuplicateRiskPolicy()
    disposition_correct = true_positive = false_positive = false_negative = 0
    known_false_clear = clean_false_review = incomplete_correct = incomplete_count = 0
    latencies: list[float] = []
    assessment_keys: list[tuple[uuid.UUID, str]] = []
    for scenario in selected:
        started = time.perf_counter()
        result = assess_duplicate_risk(
            scenario.current, list(scenario.historical), effective_policy
        )
        latencies.append((time.perf_counter() - started) * 1000)
        assessment_keys.append((scenario.current.match_run_id, effective_policy.version))
        disposition_correct += result.disposition == scenario.expected_disposition
        actual = {signal.code for signal in result.signals} & DUPLICATE_CODES
        expected = set(scenario.expected_signals) & DUPLICATE_CODES
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        if expected and result.disposition == RiskDisposition.CLEAR:
            known_false_clear += 1
        if not scenario.expected_signals and result.disposition == RiskDisposition.NEEDS_REVIEW:
            clean_false_review += 1
        if RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE in scenario.expected_signals:
            incomplete_count += 1
            incomplete_correct += (
                result.disposition == scenario.expected_disposition
                and {signal.code for signal in result.signals} == set(scenario.expected_signals)
            )
    denominator_precision = true_positive + false_positive
    denominator_recall = true_positive + false_negative
    return DuplicateRiskEvaluationReport(
        scenario_count=len(selected),
        expected_disposition_accuracy=disposition_correct / len(selected),
        duplicate_signal_precision=(
            true_positive / denominator_precision if denominator_precision else 1.0
        ),
        duplicate_signal_recall=(
            true_positive / denominator_recall if denominator_recall else 1.0
        ),
        known_duplicate_false_clear_count=known_false_clear,
        clean_invoice_false_review_count=clean_false_review,
        incomplete_assessment_accuracy=(
            incomplete_correct / incomplete_count if incomplete_count else 1.0
        ),
        duplicate_assessment_count=len(assessment_keys) - len(set(assessment_keys)),
        p50_risk_latency_ms=round(_percentile(latencies, Decimal("0.50")), 4),
        p95_risk_latency_ms=round(_percentile(latencies, Decimal("0.95")), 4),
        policy_version=effective_policy.version,
        scenario_set_version=SCENARIO_SET_VERSION,
        source_revision=_git_revision(),
        evaluated_at=datetime.now(UTC),
        python_version=platform.python_version(),
    )


def _percentile(values: list[float], percentile: Decimal) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(float(percentile) * len(ordered)) - 1)
    return ordered[index]


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


def render_duplicate_risk_report(report: DuplicateRiskEvaluationReport) -> str:
    return "\n".join(
        [
            "# Deterministic duplicate-risk evaluation",
            "",
            "Synthetic/de-identified scenarios only; these results are not production fraud-"
            "detection claims.",
            "",
            f"- Scenario count: {report.scenario_count}",
            f"- Policy version: `{report.policy_version}`",
            f"- Scenario set: `{report.scenario_set_version}`",
            f"- Source revision: `{report.source_revision}`",
            f"- Expected disposition accuracy: {report.expected_disposition_accuracy:.4f}",
            f"- Duplicate-signal precision: {report.duplicate_signal_precision:.4f}",
            f"- Duplicate-signal recall: {report.duplicate_signal_recall:.4f}",
            f"- Known-duplicate false-clear count: {report.known_duplicate_false_clear_count}",
            f"- Clean-invoice false-review count: {report.clean_invoice_false_review_count}",
            f"- Incomplete-assessment accuracy: {report.incomplete_assessment_accuracy:.4f}",
            f"- Duplicate assessment count: {report.duplicate_assessment_count}",
            f"- p50 risk latency: {report.p50_risk_latency_ms:.4f} ms",
            f"- p95 risk latency: {report.p95_risk_latency_ms:.4f} ms",
            "",
            "The engine emits explicit deterministic signals, not an opaque aggregate score. "
            "A review disposition neither rejects an invoice nor authorizes payment.",
            "",
        ]
    )


def write_duplicate_risk_report(
    path: Path, report: DuplicateRiskEvaluationReport
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "report.json").write_text(
        report.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (path / "report.md").write_text(render_duplicate_risk_report(report), encoding="utf-8")
