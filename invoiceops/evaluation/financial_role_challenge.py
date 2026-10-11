"""Offline financial-role challenge: human source roles never enter extraction."""

import json
import re
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.failure_attribution import bound, check_source
from invoiceops.evaluation.financial_summary_guard import CachedSourceExtractor
from invoiceops.evaluation.human_annotations import HumanField, HumanInvoiceAnnotation
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.real_input import (
    Aggregate,
    ObservedTextExtractor,
    Rate,
    fresh_public,
    member,
    private_path,
    quiet_extraction,
    ratio,
    source_state,
)
from invoiceops.evaluation.runner import EvaluationRunner, _length_delimited_hash
from invoiceops.extraction.financial_summary_guard import FinancialSummaryGuardExtractor
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime
from invoiceops.matching.validation import validate_invoice_financials
from invoiceops.schemas.extraction import DocumentText, ExtractionStatus, Invoice
from invoiceops.schemas.matching import CheckStatus, MatchingPolicy

type Cohort = Literal["observed_development", "new_authorized_challenge", "synthetic_contract"]
METRIC_VERSION = "financial-role-challenge-v1"


class PrintedRole(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    amount: HumanField[Decimal] = Field(default_factory=HumanField[Decimal])
    printed_label: HumanField[str] = Field(default_factory=HumanField[str])

    @model_validator(mode="after")
    def independent_evidence(self) -> "PrintedRole":
        if self.amount.status != self.printed_label.status:
            raise ValueError("Printed role requires matching amount/label coverage")
        if self.amount.status == "present" and not any(
            a.page == b.page for a in self.amount.evidence for b in self.printed_label.evidence
        ):
            raise ValueError("Printed role label and amount require a common source page")
        if self.printed_label.status == "present" and not any(
            c.isalpha() for c in (self.printed_label.value or "")
        ):
            raise ValueError("Known printed role requires a textual label")
        return self


class RoleAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    annotation_version: Literal["financial-roles-v1"]
    provenance: Literal["human", "synthetic_contract"]
    labelled_without_predictions: Literal[True]
    invoice: HumanInvoiceAnnotation
    net_subtotal: PrintedRole = Field(default_factory=PrintedRole)
    component_tax: list[PrintedRole] = Field(default_factory=list)
    gross_invoice_total: PrintedRole = Field(default_factory=PrintedRole)
    payable_balance: PrintedRole = Field(default_factory=PrintedRole)
    unknown_or_ambiguous: list[PrintedRole] = Field(default_factory=list)

    def roles(self) -> list[PrintedRole]:
        return [
            self.net_subtotal,
            *self.component_tax,
            self.gross_invoice_total,
            self.payable_balance,
            *self.unknown_or_ambiguous,
        ]


def load_annotation(body: bytes) -> tuple[HumanInvoiceAnnotation, RoleAnnotation | None]:
    """Legacy labels remain usable, but never silently acquire a gross/payable role."""
    payload = json.loads(body)
    if payload.get("annotation_version") == "human-invoice-v1":
        return HumanInvoiceAnnotation.model_validate(payload), None
    roles = RoleAnnotation.model_validate(payload)
    return roles.invoice, roles


class Outcomes(Aggregate):
    documents: int = 0
    present: int = 0
    absent: int = 0
    unannotated: int = 0
    correct: int = 0
    wrong: int = 0
    ambiguous: int = 0
    missing: int = 0
    failed_present: int = 0
    failed_documents: int = 0
    emitted: int = 0
    emitted_on_absent: int = 0
    emitted_unannotated: int = 0
    source_supported_correct: int = 0
    source_supported_role_errors: int = 0
    unresolved_emitted_evidence: int = 0
    mandatory_financial_review: int = 0
    total_incomplete_review_gate: int = 0


def role_support(role: PrintedRole, invoice: Invoice, source: DocumentText) -> bool:
    if role.amount.status != "present":
        return False
    return (
        canonical_value(invoice.total.value, "total") == canonical_value(role.amount.value, "total")
        and check_source(role.printed_label, "description", source).state == "found"
        and bound(invoice.total, check_source(role.amount, "total", source))
    )


def score(
    annotation: RoleAnnotation | None, invoice: Invoice | None, source: DocumentText | None
) -> Outcomes:
    target = annotation.gross_invoice_total.amount if annotation else HumanField[Decimal]()
    result = Outcomes(documents=1)
    setattr(result, {"not_annotated": "unannotated"}.get(target.status, target.status), 1)
    if invoice is None:
        result.failed_documents = result.mandatory_financial_review = 1
        result.total_incomplete_review_gate = 1
        result.failed_present = result.present
        return result
    result.total_incomplete_review_gate = int(invoice.total.status != ExtractionStatus.EXTRACTED)
    result.mandatory_financial_review = int(
        any(
            c.status == CheckStatus.FAILED
            for c in validate_invoice_financials(invoice, MatchingPolicy())
        )
    )
    result.emitted = int(invoice.total.status == ExtractionStatus.EXTRACTED)
    if target.status != "present":
        result.emitted_on_absent = result.emitted * result.absent
        result.emitted_unannotated = result.emitted * result.unannotated
    elif invoice.total.status == ExtractionStatus.AMBIGUOUS:
        result.ambiguous = 1
    elif invoice.total.status == ExtractionStatus.MISSING:
        result.missing = 1
    elif canonical_value(invoice.total.value, "total") == canonical_value(target.value, "total"):
        result.correct = 1
    else:
        result.wrong = 1
    if result.emitted:
        if annotation and source:
            supports = [r for r in annotation.roles() if role_support(r, invoice, source)]
            gross = role_support(annotation.gross_invoice_total, invoice, source)
            # Equal amounts or broad evidence spanning distinct roles remain unresolved.
            result.source_supported_correct = int(result.correct and gross and len(supports) == 1)
            foreign = [
                annotation.net_subtotal,
                *annotation.component_tax,
                annotation.payable_balance,
            ]
            result.source_supported_role_errors = int(
                target.status != "not_annotated"
                and not gross
                and len(supports) == 1
                and any(role_support(r, invoice, source) for r in foreign)
            )
        result.unresolved_emitted_evidence = (
            1 - result.source_supported_correct - result.source_supported_role_errors
        )
    return result


class Metrics(Aggregate):
    counts: Outcomes
    emitted_total_precision: Rate
    correct_total_recall: Rate
    role_supported_precision: Rate


def metrics(parts: list[Outcomes]) -> Metrics:
    counts = Outcomes(**{k: sum(getattr(p, k) for p in parts) for k in Outcomes.model_fields})
    if counts.documents != counts.present + counts.absent + counts.unannotated:
        raise ValueError("Coverage accounting failed")
    if counts.present != sum(
        getattr(counts, k) for k in ("correct", "wrong", "ambiguous", "missing", "failed_present")
    ):
        raise ValueError("Present gross accounting failed")
    if counts.emitted != (
        counts.correct + counts.wrong + counts.emitted_on_absent + counts.emitted_unannotated
    ) or counts.emitted != (
        counts.source_supported_correct
        + counts.source_supported_role_errors
        + counts.unresolved_emitted_evidence
    ):
        raise ValueError("Emission accounting failed")
    return Metrics(
        counts=counts,
        emitted_total_precision=ratio(
            counts.correct, counts.correct + counts.wrong + counts.emitted_on_absent
        ),
        correct_total_recall=ratio(counts.correct, counts.present),
        role_supported_precision=ratio(counts.source_supported_correct, counts.emitted),
    )


class ChallengeReport(Aggregate):
    # Loading a report without a metric version must not imply current scoring.
    metric_version: Literal["financial-role-challenge-v1"] | None = None
    cohort: Cohort
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    baseline_version: Literal["deterministic-baseline@0.2.0"] = "deterministic-baseline@0.2.0"
    guard_version: Literal["deterministic-financial-summary-guard@0.3.0"] = (
        "deterministic-financial-summary-guard@0.3.0"
    )
    documents: int
    pages: int
    ocr_documents: int
    failed_documents: int
    ocr_runtime_available: bool
    ocr_version: str | None = Field(default=None, pattern=r"^[0-9]+(?:\.[0-9]+)+$")
    baseline: Metrics
    guard: Metrics
    false_abstentions: Rate
    unchanged_non_total_documents: int
    limitations: Literal["no-population-accuracy-no-model-no-PO-matching"] = (
        "no-population-accuracy-no-model-no-PO-matching"
    )


class ChallengeSourceGuard:
    """Shared private source preflight; byte overlap never establishes independence."""

    def __init__(self, cohort: Cohort, observed_manifest: Path | None, repository: Path) -> None:
        self.observed_hashes: set[str] = set()
        self.seen: set[str] = set()
        if cohort == "new_authorized_challenge":
            if observed_manifest is None:
                raise ValueError("New challenge requires observed-corpus non-overlap reference")
            reference = private_path(observed_manifest, repository)
            self.observed_hashes = {
                sha256(
                    member(reference.parent, e.document_path, repository).read_bytes()
                ).hexdigest()
                for e in ManifestAdapter().load(reference).examples
            }

    def check(self, body: bytes) -> None:
        source_hash = sha256(body).hexdigest()
        if source_hash in self.seen or source_hash in self.observed_hashes:
            raise ValueError("Duplicate or previously observed source in challenge")
        self.seen.add(source_hash)


def run_challenge(
    manifest: Path,
    output: Path,
    diagnostics: Path,
    *,
    repository: Path,
    cohort: Cohort,
    observed_manifest: Path | None = None,
) -> ChallengeReport:
    output = fresh_public(output, repository)
    diagnostics = private_path(diagnostics, repository)
    if diagnostics.exists():
        raise FileExistsError("Private output must be fresh")
    manifest = private_path(manifest, repository)
    dataset = ManifestAdapter().load(manifest)
    source_guard = ChallengeSourceGuard(cohort, observed_manifest, repository)
    prepared = []
    fingerprints = []
    for example in dataset.examples:
        body = member(manifest.parent, example.document_path, repository).read_bytes()
        source_guard.check(body)
        labels = member(manifest.parent, example.ground_truth_path, repository).read_bytes()
        annotation, roles = load_annotation(labels)
        if cohort != "observed_development" and roles is None:
            raise ValueError("Challenge requires independently labelled printed roles")
        if roles and (roles.provenance == "synthetic_contract") != (cohort == "synthetic_contract"):
            raise ValueError("Annotation provenance does not match cohort")
        canonical = (roles or annotation).model_dump_json().encode()
        fingerprints.append(bytes.fromhex(_length_delimited_hash([body, canonical])))
        prepared.append((example, body, annotation, roles, canonical))
    baseline_parts, guard_parts, cases = [], [], []
    pages = ocr = eligible = false_abstentions = unchanged = failures = 0
    with quiet_extraction():
        runtime = inspect_ocr_runtime()
        for example, body, annotation, roles, canonical in prepared:
            observed = ObservedTextExtractor(runtime)
            baseline_result = EvaluationRunner(text_extractor=observed)._evaluate(
                example, body, annotation.legacy_truth(), canonical
            )
            baseline = baseline_result.prediction.invoice
            if (
                roles
                and observed.page_count is not None
                and any(
                    box.page >= observed.page_count
                    for r in roles.roles()
                    for f in (r.amount, r.printed_label)
                    for box in f.evidence
                )
            ):
                raise ValueError("Role annotation page outside source")
            guard_result = (
                EvaluationRunner(
                    text_extractor=CachedSourceExtractor(observed.document),
                    invoice_extractor=FinancialSummaryGuardExtractor(),
                )._evaluate(example, body, annotation.legacy_truth(), canonical)
                if observed.document
                else baseline_result
            )
            guard = guard_result.prediction.invoice
            a, b = score(roles, baseline, observed.document), score(roles, guard, observed.document)
            baseline_parts.append(a)
            guard_parts.append(b)
            eligible += a.source_supported_correct
            false_abstentions += int(
                a.source_supported_correct == 1
                and guard is not None
                and guard.total.status in (ExtractionStatus.MISSING, ExtractionStatus.AMBIGUOUS)
            )
            unchanged += int(
                bool(baseline and guard)
                and baseline is not None
                and guard is not None
                and baseline.model_dump(exclude={"total"}) == guard.model_dump(exclude={"total"})
            )
            pages += observed.page_count or 0
            ocr += int(observed.ocr_pages > 0)
            failures += int(baseline is None or guard is None)
            cases.append(
                dict(
                    document_id=example.document_id,
                    baseline=baseline_result.model_dump(mode="json"),
                    guard=guard_result.model_dump(mode="json"),
                    baseline_score=a.model_dump(),
                    guard_score=b.model_dump(),
                )
            )
    revision, state = source_state(repository)
    report = ChallengeReport(
        metric_version=METRIC_VERSION,
        cohort=cohort,
        corpus_fingerprint=_length_delimited_hash(sorted(fingerprints)),
        source_revision=revision,
        source_state=state,
        documents=len(prepared),
        pages=pages,
        ocr_documents=ocr,
        failed_documents=failures,
        ocr_runtime_available=runtime.available,
        ocr_version=(
            match.group(1)
            if runtime.version
            and (match := re.fullmatch(r"tesseract v?([0-9.]+)", runtime.version))
            else None
        ),
        baseline=metrics(baseline_parts),
        guard=metrics(guard_parts),
        false_abstentions=ratio(false_abstentions, eligible),
        unchanged_non_total_documents=unchanged,
    )
    payload = report.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    diagnostics.mkdir(parents=True, exist_ok=False)
    (diagnostics / "cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8"
    )
    (output / "report.json").write_text(payload, encoding="utf-8")
    (output / "report.md").write_text(
        "# Financial-role challenge\n\n"
        "Synthetic contracts are not independent real-world validation. The old 29-document "
        "corpus is observed development data and is reported separately. Gross invoice total "
        "is the target; payable balance is a distinct printed role, never reconstructed.\n\n"
        "Correct/wrong are normalized value outcomes on present gross labels. Precision = "
        "correct / (correct + wrong + emissions on absent); recall = correct / present, "
        "including failures. Unannotated emissions are excluded from value precision and counted "
        "separately. Role-supported precision = "
        "uniquely gross-supported correct / all emitted. Source-supported role errors require "
        "unique competing printed-role support; unresolved evidence is not a confirmed error. "
        "When the gross target is unannotated, emitted role evidence remains unresolved. "
        "False abstentions = guard missing/ambiguous / source-supported correct baseline totals. "
        "Review counts are existing pre-PO financial gates, not actual matching decisions. "
        "Independent labelling is a reviewer attestation, not evidence of inter-rater agreement."
        "\n\n```json\n" + payload + "```\n",
        encoding="utf-8",
    )
    return report
