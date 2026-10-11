"""Guarded live evaluation: paired inputs, source-labelled safety, allowlisted aggregates."""

import math
import re
import subprocess
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from invoiceops.evaluation.header_miss_audit import _no_links
from invoiceops.evaluation.live_budget import BudgetedVisionProvider, BudgetRefusal, PriceProfile
from invoiceops.evaluation.live_corpus import (
    CORPUS_VERSION,
    CellLabel,
    CorpusCase,
    load_corpus,
)
from invoiceops.evaluation.matching import is_exact_line_item
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.extraction.hybrid.fusion import (
    HEADER_FIELDS,
    LINE_FIELDS,
    FusionResult,
    fuse_invoice,
)
from invoiceops.extraction.hybrid.grounding import ground_candidate
from invoiceops.extraction.hybrid.provider import VisionProviderError
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.hybrid.router import route_extraction
from invoiceops.extraction.hybrid.schemas import FusionOutcome, RenderedPage, VisionInvoiceCandidate
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.version import (
    EXTRACTOR_VERSION,
    HYBRID_EXTRACTOR_VERSION,
    HYBRID_SCHEMA_VERSION,
    VLM_PROMPT_VERSION,
)
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import DocumentText, EvidenceSpan, ExtractionStatus, Invoice
from invoiceops.schemas.matching import (
    MatchDecision,
    MatchingPolicy,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
)

type HeaderName = Literal["invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"]
type Partition = Literal["all", "development", "unseen"]
type InputType = Literal["pdf", "png"]


class AggregateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fraction(AggregateModel):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None


def fraction(numerator: int, denominator: int) -> Fraction:
    return Fraction(
        numerator=numerator,
        denominator=denominator,
        rate=numerator / denominator if denominator else None,
    )


class ModeCounts(AggregateModel):
    documents: int = 0
    header_exact_match: dict[HeaderName, Fraction] = Field(default_factory=dict)
    line_tp: int = 0
    line_fp: int = 0
    line_fn: int = 0
    predicted_lines: int = 0
    labelled_lines: int = 0
    line_precision: Fraction = Field(default_factory=lambda: fraction(0, 0))
    line_recall: Fraction = Field(default_factory=lambda: fraction(0, 0))
    line_f1: Fraction = Field(default_factory=lambda: fraction(0, 0))
    review_documents: int = 0
    matched_documents: int = 0
    expected_review_documents: int = 0
    false_automatic_matches: Fraction = Field(default_factory=lambda: fraction(0, 0))
    p50_total_latency_ms: float = 0
    p95_total_latency_ms: float = 0


class SafetyCounts(AggregateModel):
    candidate_value_attempts: int = 0
    grounded_values: int = 0
    grounded_value_acceptance: Fraction = Field(default_factory=lambda: fraction(0, 0))
    candidate_rows: int = 0
    associated_rows: int = 0
    deterministic_rows_considered: int = 0
    correct_associations: int = 0
    incorrect_associations: int = 0
    unscorable_associations: int = 0
    row_association_precision: Fraction = Field(default_factory=lambda: fraction(0, 0))
    row_association_coverage: Fraction = Field(default_factory=lambda: fraction(0, 0))
    deterministic_row_association_coverage: Fraction = Field(default_factory=lambda: fraction(0, 0))
    row_abstention: Fraction = Field(default_factory=lambda: fraction(0, 0))
    disagreement_cells: int = 0
    promoted_cells: int = 0
    numeric_promoted_cells: int = 0
    wrong_financial_value_promotions: int = 0
    wrong_financial_role_promotions: int = 0
    line_promoted_cells: int = 0
    false_value_promotions: Fraction = Field(default_factory=lambda: fraction(0, 0))
    false_financial_promotions: Fraction = Field(default_factory=lambda: fraction(0, 0))
    false_cross_row_promotions: Fraction = Field(default_factory=lambda: fraction(0, 0))
    unscorable_promotions: int = 0
    unscorable_numeric_promotions: int = 0
    unscorable_line_promotions: int = 0
    unresolved_row_documents: int = 0
    unresolved_row_review_documents: int = 0
    unresolved_row_false_automatic_matches: Fraction = Field(default_factory=lambda: fraction(0, 0))
    eligible_documents: int = 0
    provider_requests: int = 0
    successful_responses: int = 0
    provider_failures: int = 0
    budget_refused_documents: int = 0
    provider_failure_rate: Fraction = Field(default_factory=lambda: fraction(0, 0))
    p50_provider_latency_ms: float | None = None
    p95_provider_latency_ms: float | None = None


class PartitionMetrics(AggregateModel):
    deterministic: ModeCounts
    hybrid: ModeCounts
    safety: SafetyCounts


class UsageCounts(AggregateModel):
    requests: int
    known_usage_requests: int
    unknown_usage_requests: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    complete: bool
    known_usage_cost_usd: str
    estimated_total_cost_usd: str | None
    spending_limit_usd: str
    accounted_cost_upper_bound_usd: str
    per_request_reserved_upper_bound_usd: str
    max_output_tokens: int
    input_charge_token_bound: int
    accounting_halted: bool


class LiveReport(AggregateModel):
    metric_version: Literal["synthetic-source-safety-v2"] | None = None
    mode: Literal["hybrid-live", "fake-provider", "synthetic-local"]
    local_provider_version: Literal["label-guided-stub-v1"] | None = None
    source_input_mode: Literal["native", "synthetic-scan-tokens"] = "native"
    corpus_version: Literal["synthetic-live-financial-roles-v1"]
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_seed: int
    partition: Partition
    documents: int
    pages: int
    ocr_documents: int
    ocr_engine: Literal["tesseract"] | None = None
    ocr_engine_version: str | None = Field(default=None, pattern=r"^tesseract [0-9A-Za-z.+_-]+$")
    ocr_version_source: Literal["runtime-cli"] | None = None
    ocr_backend: Literal["pymupdf-tesseract"] | None = None
    ocr_backend_version: str | None = Field(default=None, pattern=r"^[0-9]+(?:\.[0-9]+)+$")
    synthetic_scan_documents: int = 0
    max_documents: int
    max_pages: int
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    deterministic_version: Literal["0.2.0"]
    hybrid_version: Literal["0.5.0"]
    schema_version: Literal["invoice-v2"]
    prompt_version: Literal["invoice-vision-v1"]
    matching_policy: Literal["matching-v3"]
    price_assumptions: PriceProfile | None
    metrics: dict[Partition, PartitionMetrics]
    metrics_by_input_type: dict[InputType, PartitionMetrics] = Field(default_factory=dict)
    usage: UsageCounts
    limitations: list[str]


def _percentile(values: list[float], p: float) -> float:
    return sorted(values)[max(0, math.ceil(p * len(values)) - 1)] if values else 0


def _hits(
    spans: list[EvidenceSpan] | tuple[EvidenceSpan, ...], labels: tuple[CellLabel, ...]
) -> list[CellLabel]:
    def contains_center(outer: EvidenceSpan | CellLabel, inner: EvidenceSpan | CellLabel) -> bool:
        return (
            outer.bbox.x0 <= (inner.bbox.x0 + inner.bbox.x1) / 2 <= outer.bbox.x1
            and outer.bbox.y0 <= (inner.bbox.y0 + inner.bbox.y1) / 2 <= outer.bbox.y1
        )

    # Deterministic evidence can include a printed label plus its amount. Its center may lie
    # in the label prefix, outside the amount-only annotation. Accept containment in either
    # direction; retain ALL hits so competing roles/rows remain unsafe. Mere edge overlap is
    # insufficient, and page identity is required. This changes scoring, never extraction.
    return [
        label
        for label in labels
        if any(
            span.page == label.page
            and (contains_center(label, span) or contains_center(span, label))
            for span in spans
        )
    ]


def _row(spans: list[EvidenceSpan] | tuple[EvidenceSpan, ...], case: CorpusCase) -> int | None:
    # A description span may contain a wrapped/expanded phrase. Its union-box center can lie
    # outside the labelled description. Use unique overlap, never values or row order.
    found = {
        label.row
        for label in case.labels
        if label.role == "description"
        and any(
            span.page == label.page
            and min(span.bbox.x1, label.bbox.x1) > max(span.bbox.x0, label.bbox.x0)
            and min(span.bbox.y1, label.bbox.y1) > max(span.bbox.y0, label.bbox.y0)
            for span in spans
        )
    }
    return next(iter(found)) if len(found) == 1 else None


def _role_correct(name: str, spans: list[EvidenceSpan], case: CorpusCase, row: int | None) -> bool:
    labels = _hits(spans, case.labels)
    return bool(labels) and all(label.role == name and label.row == row for label in labels)


def _po(case: CorpusCase) -> PurchaseOrderRead:
    po_id = uuid.UUID(int=1)
    return PurchaseOrderRead(
        id=po_id,
        external_po_number="SYNTHETIC-EVAL",
        vendor_name=None,
        currency="USD",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        lines=[
            PurchaseOrderLineRead(
                id=uuid.UUID(int=i + 2),
                purchase_order_id=po_id,
                line_number=str(i + 1),
                description=line.description or "",
                ordered_quantity=line.quantity or Decimal(0),
                unit_price=line.unit_price or Decimal(0),
                line_total=line.line_total,
            )
            for i, line in enumerate(case.purchase_order_lines)
        ],
    )


def mode_counts(
    cases: list[CorpusCase], invoices: list[Invoice], latencies: list[float]
) -> ModeCounts:
    count = ModeCounts(documents=len(cases))
    false_auto = 0
    for name in HEADER_FIELDS:
        count.header_exact_match[cast(HeaderName, name)] = fraction(
            sum(
                getattr(invoice, name).status == ExtractionStatus.EXTRACTED
                and canonical_value(getattr(invoice, name).value, name)
                == canonical_value(getattr(case.truth, name), name)
                for case, invoice in zip(cases, invoices, strict=True)
            ),
            len(cases),
        )
    for case, invoice in zip(cases, invoices, strict=True):
        # Exact rows are a multiset: order never determines precision or duplicate credit.
        unused = list(case.truth.line_items)
        exact = 0
        for line in invoice.line_items:
            found = next(
                (i for i, truth in enumerate(unused) if is_exact_line_item(truth, line)), None
            )
            if found is not None:
                exact += 1
                unused.pop(found)
        count.line_tp += exact
        count.line_fp += len(invoice.line_items) - exact
        count.line_fn += len(case.truth.line_items) - exact
        count.predicted_lines += len(invoice.line_items)
        count.labelled_lines += len(case.truth.line_items)
        wrong = exact != len(invoice.line_items) or exact != len(case.truth.line_items)
        for name in HEADER_FIELDS:
            field = getattr(invoice, name)
            wrong |= field.status != ExtractionStatus.EXTRACTED or canonical_value(
                field.value, name
            ) != canonical_value(getattr(case.truth, name), name)
            if name in {"subtotal", "tax", "total"} and field.status == ExtractionStatus.EXTRACTED:
                wrong |= not _role_correct(name, field.evidence, case, None)
        for line in invoice.line_items:
            row = _row(line.description.evidence, case)
            for name in LINE_FIELDS[1:]:
                field = getattr(line, name)
                if field.status == ExtractionStatus.EXTRACTED:
                    wrong |= row is None or not _role_correct(name, field.evidence, case, row)
        expected_review = case.expected_review or wrong
        matched = match_invoice(invoice, _po(case)).decision == MatchDecision.MATCHED
        count.matched_documents += matched
        count.review_documents += not matched
        count.expected_review_documents += expected_review
        false_auto += matched and expected_review
    count.line_precision = fraction(count.line_tp, count.predicted_lines)
    count.line_recall = fraction(count.line_tp, count.labelled_lines)
    count.line_f1 = fraction(2 * count.line_tp, 2 * count.line_tp + count.line_fp + count.line_fn)
    count.false_automatic_matches = fraction(false_auto, count.expected_review_documents)
    count.p50_total_latency_ms = _percentile(latencies, 0.5)
    count.p95_total_latency_ms = _percentile(latencies, 0.95)
    return count


def audit_fusion(
    case: CorpusCase,
    baseline: Invoice,
    document: DocumentText,
    candidate: VisionInvoiceCandidate,
    fusion: FusionResult,
) -> SafetyCounts:
    count = SafetyCounts(
        candidate_rows=len(candidate.line_items), associated_rows=len(fusion.row_associations)
    )
    count.deterministic_rows_considered = len(baseline.line_items)
    claimed = [(name, getattr(candidate, name)) for name in HEADER_FIELDS]
    claimed += [(name, getattr(row, name)) for row in candidate.line_items for name in LINE_FIELDS]
    for name, field in claimed:
        if field.raw_value is not None:
            count.candidate_value_attempts += 1
            count.grounded_values += ground_candidate(name, field, document).grounded
    for d, c in fusion.row_associations.items():
        expected = _row(baseline.line_items[d].description.evidence, case)
        candidate_anchor = ground_candidate(
            "description", candidate.line_items[c].description, document
        )
        actual = _row(candidate_anchor.evidence, case)
        if expected is None or actual is None:
            count.unscorable_associations += 1
        elif expected == actual:
            count.correct_associations += 1
        else:
            count.incorrect_associations += 1
    false_value = false_financial = false_cross = 0
    for path, outcome in fusion.outcomes.items():
        count.disagreement_cells += outcome == FusionOutcome.DISAGREEMENT_ABSTAINED
        if outcome != FusionOutcome.VLM_FILLED:
            continue
        count.promoted_cells += 1
        if path.startswith("line_items."):
            count.line_promoted_cells += 1
            _, index, name = path.split(".")
            row = _row(baseline.line_items[int(index)].description.evidence, case)
            field = getattr(fusion.invoice.line_items[int(index)], name)
            truth_value = getattr(case.truth.line_items[row], name) if row is not None else None
            hits = _hits(field.evidence, case.labels)
            scorable = row is not None and bool(hits)
            false_cross += row is not None and any(
                label.row is not None and label.row != row for label in hits
            )
            count.unscorable_line_promotions += not scorable
        else:
            name, row = path, None
            field = getattr(fusion.invoice, name)
            truth_value = getattr(case.truth, name)
            scorable = bool(_hits(field.evidence, case.labels))
        numeric = name in {"subtotal", "tax", "total", "quantity", "unit_price", "line_total"}
        valid = canonical_value(field.value, name) == canonical_value(
            truth_value, name
        ) and _role_correct(name, field.evidence, case, row)
        count.unscorable_promotions += not scorable
        count.unscorable_numeric_promotions += numeric and not scorable
        false_value += scorable and not valid
        count.numeric_promoted_cells += numeric
        count.wrong_financial_value_promotions += (
            scorable
            and numeric
            and canonical_value(field.value, name) != canonical_value(truth_value, name)
        )
        count.wrong_financial_role_promotions += (
            scorable and numeric and not _role_correct(name, field.evidence, case, row)
        )
        false_financial += scorable and numeric and not valid
    count.false_value_promotions = fraction(false_value, count.promoted_cells)
    count.false_financial_promotions = fraction(false_financial, count.numeric_promoted_cells)
    count.false_cross_row_promotions = fraction(false_cross, count.line_promoted_cells)
    count.unresolved_row_documents = int(bool(fusion.invoice.extraction_issues))
    if count.unresolved_row_documents:
        matched = match_invoice(fusion.invoice, _po(case)).decision == MatchDecision.MATCHED
        count.unresolved_row_review_documents = int(not matched)
        count.unresolved_row_false_automatic_matches = fraction(int(matched), 1)
    return count


def _combine(counts: list[SafetyCounts], latencies: list[float]) -> SafetyCounts:
    counters: Counter[str] = Counter()
    for count in counts:
        for name in SafetyCounts.model_fields:
            value = getattr(count, name)
            if type(value) is int:
                counters[name] += value
    result = SafetyCounts(**dict(counters))
    for name in (
        "false_value_promotions",
        "false_financial_promotions",
        "false_cross_row_promotions",
        "unresolved_row_false_automatic_matches",
    ):
        setattr(
            result,
            name,
            fraction(
                sum(getattr(c, name).numerator for c in counts),
                sum(getattr(c, name).denominator for c in counts),
            ),
        )
    result.grounded_value_acceptance = fraction(
        result.grounded_values, result.candidate_value_attempts
    )
    result.row_association_precision = fraction(result.correct_associations, result.associated_rows)
    result.row_association_coverage = fraction(result.associated_rows, result.candidate_rows)
    result.deterministic_row_association_coverage = fraction(
        result.associated_rows,
        result.deterministic_rows_considered,
    )
    result.row_abstention = fraction(
        result.candidate_rows - result.associated_rows, result.candidate_rows
    )
    result.provider_failure_rate = fraction(result.provider_failures, result.provider_requests)
    result.p50_provider_latency_ms = _percentile(latencies, 0.5) if latencies else None
    result.p95_provider_latency_ms = _percentile(latencies, 0.95) if latencies else None
    return result


def output_preflight(output: Path, repository: Path) -> Path:
    _no_links(output.absolute())
    resolved = output.resolve()
    root = repository.resolve() / "evals" / "reports" / "hybrid"
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Aggregate output must be a fresh hybrid report directory")
    if resolved.exists():
        raise FileExistsError("Aggregate report directory already exists")
    return resolved


def _source() -> tuple[str, Literal["clean", "working-tree changes", "unknown"]]:
    try:
        source_root = Path(__file__).resolve().parents[2]
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=source_root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return (
            revision if re.fullmatch("[0-9a-f]{40}", revision) else "unknown",
            "working-tree changes" if dirty else "clean",
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown"


def _write_files(output: Path, report: LiveReport) -> None:
    payload = report.model_dump_json(indent=2) + "\n"
    (output / "report.json").write_text(payload, encoding="utf-8")
    # The same allowlisted aggregate tree is visible standalone, with exact denominators.
    (output / "report.md").write_text(
        "# Guarded synthetic hybrid benchmark\n\n"
        "Aggregate counts only. Rates with zero denominators are null. "
        "This is synthetic evaluation, not production or DocILE evidence.\n\n"
        "```json\n" + payload + "```\n",
        encoding="utf-8",
    )


def run_hybrid_live_manifest(
    manifest_path: Path,
    provider: BudgetedVisionProvider,
    renderer: PageRenderer,
    *,
    allow_live: bool,
    max_documents: int,
    max_pages: int,
    output_dir: Path,
    repository: Path,
    partition: Partition = "all",
    allow_holdout: bool = False,
    text_extractor: DocumentTextExtractor | None = None,
) -> LiveReport:
    if not allow_live:
        raise ValueError("Live benchmark requires explicit authorization")
    return _run_hybrid_manifest(
        manifest_path,
        provider,
        renderer,
        max_documents=max_documents,
        max_pages=max_pages,
        output_dir=output_dir,
        repository=repository,
        partition=partition,
        allow_holdout=allow_holdout,
        text_extractor=text_extractor,
    )


def _run_hybrid_manifest(
    manifest_path: Path,
    provider: BudgetedVisionProvider,
    renderer: PageRenderer,
    *,
    max_documents: int,
    max_pages: int,
    output_dir: Path,
    repository: Path,
    partition: Partition = "all",
    allow_holdout: bool = False,
    text_extractor: DocumentTextExtractor | None = None,
    local_source_mode: Literal["native", "synthetic-scan-tokens"] | None = None,
) -> LiveReport:
    if local_source_mode is not None and not provider.fake:
        raise ValueError("Local evaluation requires an in-process fake provider")
    if max_documents <= 0 or max_pages <= 0:
        raise ValueError("Document and page limits must be positive")
    if text_extractor is not None and not provider.fake:
        raise ValueError("Custom text/OCR extraction is permitted only for fake-provider tests")
    output = output_preflight(output_dir, repository)
    cases, fingerprint, seed = load_corpus(manifest_path, repository, partition)
    if any(c.split == "unseen" for c in cases) and not allow_holdout:
        raise ValueError("Reserved unseen layouts require explicit --allow-holdout")
    if len(cases) > max_documents or sum(c.pages for c in cases) > max_pages:
        raise ValueError("Corpus exceeds document/page limits; no request permitted")
    ocr_engine_version = None
    if text_extractor is None:
        if any(c.content_type == "image/png" for c in cases):
            runtime = inspect_ocr_runtime()
            require_ocr_runtime(runtime)
            if runtime.version is None or not re.fullmatch(
                r"tesseract [0-9A-Za-z.+_-]+", runtime.version
            ):
                raise ValueError("OCR runtime version is unavailable or unsafe to export")
            ocr_engine_version = runtime.version
        text_extractor = DocumentTextExtractor()
    extractor = DeterministicInvoiceExtractor()
    documents: list[DocumentText] = []
    baselines: list[Invoice] = []
    rendered: list[list[RenderedPage]] = []
    render_latencies: list[float] = []
    deterministic_latencies: list[float] = []
    # Preprocess/render the ENTIRE selected corpus before spending anything (including OCR).
    for case in cases:
        started = time.perf_counter()
        document = text_extractor.extract(case.body, case.content_type)
        documents.append(document)
        baselines.append(extractor.extract(document))
        deterministic_latencies.append((time.perf_counter() - started) * 1000)
        render_started = time.perf_counter()
        rendered.append(renderer.render(case.body, case.content_type))
        render_latencies.append((time.perf_counter() - render_started) * 1000)
    output.mkdir(parents=True, exist_ok=False)
    hybrids: list[Invoice] = []
    hybrid_latencies: list[float] = []
    provider_latencies: list[float | None] = []
    audits: list[SafetyCounts] = []
    for case, document, baseline, pages, baseline_latency, render_latency in zip(
        cases,
        documents,
        baselines,
        rendered,
        deterministic_latencies,
        render_latencies,
        strict=True,
    ):
        audit = SafetyCounts()
        invoice = baseline
        started = time.perf_counter()
        provider_latency = None
        audit_latency = 0.0
        invoked = route_extraction(baseline, document).invoke_vlm
        if invoked:
            audit.eligible_documents = 1
            before = provider.ledger.calls
            call_started = time.perf_counter()
            try:
                response = provider.extract(pages, document)
                provider_latency = (time.perf_counter() - call_started) * 1000
                fusion = fuse_invoice(baseline, response.candidate, document)
                audit_started = time.perf_counter()
                audit = audit_fusion(case, baseline, document, response.candidate, fusion)
                audit_latency = (time.perf_counter() - audit_started) * 1000
                audit.eligible_documents = 1
                audit.successful_responses = 1
                invoice = fusion.invoice
            except BudgetRefusal:
                audit.budget_refused_documents = 1
            except VisionProviderError:
                audit.provider_failures = 1
            audit.provider_requests = provider.ledger.calls - before
            if audit.provider_requests and provider_latency is None:
                provider_latency = (time.perf_counter() - call_started) * 1000
        hybrids.append(invoice)
        audits.append(audit)
        provider_latencies.append(provider_latency)
        hybrid_latencies.append(
            baseline_latency
            + (render_latency if invoked else 0)
            + (time.perf_counter() - started) * 1000
            - audit_latency,
        )

    def summarize(indexes: list[int]) -> PartitionMetrics:
        selected = [cases[i] for i in indexes]
        return PartitionMetrics(
            deterministic=mode_counts(
                selected,
                [baselines[i] for i in indexes],
                [deterministic_latencies[i] for i in indexes],
            ),
            hybrid=mode_counts(
                selected, [hybrids[i] for i in indexes], [hybrid_latencies[i] for i in indexes]
            ),
            safety=_combine(
                [audits[i] for i in indexes],
                [p for i in indexes if (p := provider_latencies[i]) is not None],
            ),
        )

    metrics: dict[Partition, PartitionMetrics] = {}
    for split in ("all", "development", "unseen"):
        indexes = [i for i, c in enumerate(cases) if split == "all" or c.split == split]
        if indexes:
            metrics[split] = summarize(indexes)
    metrics_by_input_type: dict[InputType, PartitionMetrics] = {}
    for kind, content_type in (("pdf", "application/pdf"), ("png", "image/png")):
        indexes = [i for i, case in enumerate(cases) if case.content_type == content_type]
        if indexes:
            metrics_by_input_type[cast(InputType, kind)] = summarize(indexes)
    ledger = provider.ledger
    revision, state = _source()
    report = LiveReport(
        metric_version="synthetic-source-safety-v2",
        mode="fake-provider" if provider.fake else "hybrid-live",
        corpus_version=CORPUS_VERSION,
        corpus_fingerprint=fingerprint,
        corpus_seed=seed,
        partition=partition,
        documents=len(cases),
        pages=sum(c.pages for c in cases),
        ocr_documents=sum(d.used_ocr for d in documents),
        ocr_engine="tesseract" if ocr_engine_version is not None else None,
        ocr_engine_version=ocr_engine_version,
        ocr_version_source="runtime-cli" if ocr_engine_version is not None else None,
        ocr_backend="pymupdf-tesseract" if ocr_engine_version is not None else None,
        ocr_backend_version=pymupdf.VersionBind if ocr_engine_version is not None else None,
        max_documents=max_documents,
        max_pages=max_pages,
        source_revision=revision,
        source_state=state,
        deterministic_version=EXTRACTOR_VERSION,
        hybrid_version=HYBRID_EXTRACTOR_VERSION,
        schema_version=HYBRID_SCHEMA_VERSION,
        prompt_version=VLM_PROMPT_VERSION,
        matching_policy=MatchingPolicy().version,
        price_assumptions=ledger.profile,
        metrics=metrics,
        metrics_by_input_type=metrics_by_input_type,
        usage=UsageCounts(
            requests=ledger.calls,
            known_usage_requests=ledger.known_usage_calls,
            unknown_usage_requests=ledger.unknown_usage_calls,
            input_tokens=ledger.input_tokens,
            output_tokens=ledger.output_tokens,
            total_tokens=ledger.total_tokens,
            complete=not ledger.unknown_usage_calls,
            known_usage_cost_usd=str(ledger.known_cost),
            estimated_total_cost_usd=None if ledger.unknown_usage_calls else str(ledger.known_cost),
            spending_limit_usd=str(ledger.limit),
            accounted_cost_upper_bound_usd=str(ledger.accounted_upper),
            per_request_reserved_upper_bound_usd=str(ledger.request_bound),
            max_output_tokens=ledger.max_output_tokens,
            input_charge_token_bound=ledger.input_charge_bound,
            accounting_halted=ledger.halted,
        ),
        limitations=[
            "Synthetic layouts only; no live quality is inferred from fake-provider tests.",
            "Unseen families are reserved layouts, not a population or independent "
            "business holdout.",
            "Grounding validates copied values, not financial semantics; role errors are "
            "measured against source labels.",
            "Association precision counts unscorable accepted associations against "
            "precision; they are also shown separately.",
            "Client admission bound covers this process's standard USD token charges at "
            "the confirmed snapshot only.",
            "No taxes, currency conversion, unrelated account traffic or future price "
            "changes are included.",
            "No SDK/application retries or tools; unknown billing retains a full "
            "reservation and stops further requests.",
            "Cached input is charged at the uncached rate: known-usage cost is a "
            "conservative estimate, not an invoice.",
            "Budget-skipped and failed documents retain deterministic output and remain "
            "in paired denominators.",
            "End-to-end OCR needs the guarded Tesseract runtime; fake OCR is test-only.",
            "OCR engine version is the runtime CLI readiness version; native text extraction "
            "uses integrated PyMuPDF/Tesseract. Its backend version is recorded separately; "
            "the integrated Tesseract library version is not exposed by this API.",
            "Routing is hybrid-routed 0.5.0; complete unrouted documents are not sent to "
            "the provider.",
        ],
    )
    if local_source_mode is not None:
        report.mode = "synthetic-local"
        report.local_provider_version = "label-guided-stub-v1"
        report.source_input_mode = local_source_mode
        if local_source_mode == "synthetic-scan-tokens":
            report.synthetic_scan_documents = report.ocr_documents
            report.ocr_documents = 0
        report.price_assumptions = None
        # Ledger reservations above are simulated admission accounting, never billed usage.
        report.usage = UsageCounts(
            requests=ledger.calls,
            known_usage_requests=ledger.calls,
            unknown_usage_requests=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            complete=True,
            known_usage_cost_usd="0",
            estimated_total_cost_usd="0",
            spending_limit_usd="0",
            accounted_cost_upper_bound_usd="0",
            per_request_reserved_upper_bound_usd="0",
            max_output_tokens=0,
            input_charge_token_bound=0,
            accounting_halted=False,
        )
        report.limitations = [
            "No model, SDK, credentials or network client is initialized; zero API calls and cost.",
            "Requests and response counts denote local fixture invocations, "
            "not provider API calls.",
            "Label-guided oracle candidates exercise grounding/fusion; these are not model "
            "accuracy, generalization, provider latency or token-usage measurements.",
            "Synthetic scan tokens come from corpus labels only when explicitly selected; "
            "they are not measured OCR output. PDFs use native embedded-text extraction.",
            "Ambiguous/missing roles remain null; candidates do not infer values from arithmetic.",
            *[
                limitation
                for limitation in report.limitations
                if not any(
                    phrase in limitation
                    for phrase in (
                        "Client admission",
                        "No taxes",
                        "No SDK/application",
                        "Cached input",
                        "fake OCR is test-only",
                    )
                )
            ],
        ]
    _write_files(output, report)
    return report
