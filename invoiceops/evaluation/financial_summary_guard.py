"""Offline paired totals evaluation; annotations are used only by the scorer."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.failure_attribution import bound, check_source
from invoiceops.evaluation.human_annotations import HumanInvoiceAnnotation
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.real_input import (
    Aggregate,
    ObservedTextExtractor,
    fresh_public,
    member,
    private_path,
    quiet_extraction,
    source_state,
)
from invoiceops.evaluation.runner import EvaluationRunner, _length_delimited_hash
from invoiceops.extraction.financial_summary_guard import (
    GUARD_NAME,
    GUARD_VERSION,
    FinancialSummaryGuardExtractor,
)
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.matching.validation import validate_invoice_financials
from invoiceops.schemas.extraction import DocumentText, ExtractionStatus, Invoice
from invoiceops.schemas.matching import CheckStatus, MatchingPolicy


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
    correct_absence: int = 0
    false_on_absent: int = 0
    failed_documents: int = 0
    wrong_equals_subtotal: int = 0
    location_supported_role_errors: int = 0
    mandatory_financial_review: int = 0
    total_incomplete_review_gate: int = 0


class PairedReport(Aggregate):
    metric_version: Literal["financial-summary-guard-paired-v1"] = (
        "financial-summary-guard-paired-v1"
    )
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    baseline_name: Literal["deterministic-baseline"] = "deterministic-baseline"
    baseline_version: Literal["0.2.0"] = "0.2.0"
    candidate_name: Literal["deterministic-financial-summary-guard"] = GUARD_NAME
    candidate_version: Literal["0.3.0"] = GUARD_VERSION
    documents: int
    pages: int
    ocr_documents: int
    baseline: Outcomes
    candidate: Outcomes
    added_abstentions: int
    added_mandatory_review: int
    unchanged_non_total_documents: int
    unchanged_invoice_number_documents: int
    unchanged_invoice_date_documents: int
    unchanged_row_documents: int
    matched_summary: Literal["not evaluated: no authorized PO/receipt corpus"] = (
        "not evaluated: no authorized PO/receipt corpus"
    )
    limitations: Literal["observed-development-deterministic-only-no-hybrid-claim"] = (
        "observed-development-deterministic-only-no-hybrid-claim"
    )


class CachedSourceExtractor(DocumentTextExtractor):
    """Reuse actual native-extracted source, never annotation-derived tokens."""

    def __init__(self, document: DocumentText) -> None:
        super().__init__()
        self.document = document

    def extract(self, body: bytes, content_type: str) -> DocumentText:
        return self.document


def score(
    annotation: HumanInvoiceAnnotation, invoice: Invoice | None, document: DocumentText | None
) -> Outcomes:
    result = Outcomes(
        documents=1,
        present=int(annotation.total.status == "present"),
        absent=int(annotation.total.status == "absent"),
        unannotated=int(annotation.total.status == "not_annotated"),
    )
    if invoice is None:
        result.failed_documents = 1
        result.failed_present = result.present
        result.mandatory_financial_review = 1
        result.total_incomplete_review_gate = 1
        return result
    result.total_incomplete_review_gate = int(invoice.total.status != ExtractionStatus.EXTRACTED)
    result.mandatory_financial_review = int(
        any(
            c.status == CheckStatus.FAILED
            for c in validate_invoice_financials(invoice, MatchingPolicy())
        )
    )
    if annotation.total.status == "absent":
        result.correct_absence = int(invoice.total.status != ExtractionStatus.EXTRACTED)
        result.false_on_absent = 1 - result.correct_absence
    elif annotation.total.status == "present":
        if invoice.total.status == ExtractionStatus.AMBIGUOUS:
            result.ambiguous = 1
        elif invoice.total.status == ExtractionStatus.MISSING:
            result.missing = 1
        elif canonical_value(invoice.total.value, "total") == canonical_value(
            annotation.total.value, "total"
        ):
            result.correct = 1
        else:
            result.wrong = 1
            if annotation.subtotal.status == "present" and canonical_value(
                invoice.total.value, "total"
            ) == canonical_value(annotation.subtotal.value, "total"):
                result.wrong_equals_subtotal = 1
                if document:
                    result.location_supported_role_errors = int(
                        bound(
                            invoice.total, check_source(annotation.subtotal, "subtotal", document)
                        )
                    )
    return result


def merge(parts: list[Outcomes]) -> Outcomes:
    result = Outcomes(**{key: sum(getattr(p, key) for p in parts) for key in Outcomes.model_fields})
    if (
        result.present
        != result.correct + result.wrong + result.ambiguous + result.missing + result.failed_present
    ):
        raise ValueError("Present total accounting failed")
    if result.documents != result.present + result.absent + result.unannotated:
        raise ValueError("Label accounting failed")
    return result


def run_pair(manifest: Path, output: Path, diagnostics: Path, *, repository: Path) -> PairedReport:
    output = fresh_public(output, repository)
    diagnostics = private_path(diagnostics, repository)
    if diagnostics.exists():
        raise FileExistsError("Private output must be fresh")
    manifest = private_path(manifest, repository)
    dataset = ManifestAdapter().load(manifest)
    if dataset.examples[0].split != "development":
        raise ValueError("This comparison uses observed development data only")
    prepared = []
    fingerprints = []
    for example in dataset.examples:
        body = member(manifest.parent, example.document_path, repository).read_bytes()
        annotation = HumanInvoiceAnnotation.model_validate_json(
            member(manifest.parent, example.ground_truth_path, repository).read_bytes()
        )
        canonical = annotation.model_dump_json().encode()
        fingerprints.append(bytes.fromhex(_length_delimited_hash([body, canonical])))
        prepared.append((example, body, annotation, canonical))
    baseline_parts, candidate_parts, cases = [], [], []
    pages = ocr = abstentions = reviews = unchanged = numbers = dates = rows = 0
    with quiet_extraction():
        runtime = inspect_ocr_runtime()
        for example, body, annotation, canonical in prepared:
            observed = ObservedTextExtractor(runtime)
            baseline_result = EvaluationRunner(text_extractor=observed)._evaluate(
                example, body, annotation.legacy_truth(), canonical
            )
            baseline = baseline_result.prediction.invoice
            if observed.page_count is not None and any(
                box.page >= observed.page_count
                for label in [
                    *(
                        getattr(annotation, n)
                        for n in (
                            "invoice_number",
                            "invoice_date",
                            "currency",
                            "subtotal",
                            "tax",
                            "total",
                        )
                    ),
                    *(
                        getattr(r, n)
                        for r in annotation.line_items.rows
                        for n in ("description", "quantity", "unit_price", "line_total")
                    ),
                ]
                for box in label.evidence
            ):
                raise ValueError("Annotation page outside source")
            candidate_result = (
                EvaluationRunner(
                    text_extractor=CachedSourceExtractor(observed.document),
                    invoice_extractor=FinancialSummaryGuardExtractor(),
                )._evaluate(example, body, annotation.legacy_truth(), canonical)
                if observed.document
                else baseline_result
            )
            candidate = candidate_result.prediction.invoice
            base_score, candidate_score = (
                score(annotation, baseline, observed.document),
                score(annotation, candidate, observed.document),
            )
            baseline_parts.append(base_score)
            candidate_parts.append(candidate_score)
            if baseline and candidate:
                abstentions += int(
                    baseline.total.status == ExtractionStatus.EXTRACTED
                    and candidate.total.status != ExtractionStatus.EXTRACTED
                )
                numbers += int(baseline.invoice_number == candidate.invoice_number)
                dates += int(baseline.invoice_date == candidate.invoice_date)
                rows += int(baseline.line_items == candidate.line_items)
                unchanged += int(
                    baseline.model_dump(exclude={"total"})
                    == candidate.model_dump(exclude={"total"})
                )
            reviews += int(
                candidate_score.mandatory_financial_review > base_score.mandatory_financial_review
            )
            pages += observed.page_count or 0
            ocr += int(observed.ocr_pages > 0)
            cases.append(
                dict(
                    document_id=example.document_id,
                    baseline=baseline_result.model_dump(mode="json"),
                    candidate=candidate_result.model_dump(mode="json"),
                    baseline_score=base_score.model_dump(),
                    candidate_score=candidate_score.model_dump(),
                )
            )
    revision, state = source_state(repository)
    report = PairedReport(
        corpus_fingerprint=_length_delimited_hash(sorted(fingerprints)),
        source_revision=revision,
        source_state=state,
        documents=len(prepared),
        pages=pages,
        ocr_documents=ocr,
        baseline=merge(baseline_parts),
        candidate=merge(candidate_parts),
        added_abstentions=abstentions,
        added_mandatory_review=reviews,
        unchanged_non_total_documents=unchanged,
        unchanged_invoice_number_documents=numbers,
        unchanged_invoice_date_documents=dates,
        unchanged_row_documents=rows,
    )
    payload = report.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    diagnostics.mkdir(parents=True, exist_ok=False)
    (diagnostics / "cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8"
    )
    (output / "report.json").write_text(payload, encoding="utf-8")
    (output / "report.md").write_text(
        "# Opt-in deterministic financial-summary guard\n\n"
        "Counts use present total labels as the outcome denominator, all documents for "
        "review/unchanged outputs, and emitted wrong totals for the role-error subset. "
        "Financial review is the existing mandatory pre-PO validation gate; actual PO matching "
        "and payment decisions are not evaluated. This observed corpus is development data, "
        "not a holdout. No hybrid/VLM fix or live-provider claim.\n\n```json\n" + payload + "```\n",
        encoding="utf-8",
    )
    return report
