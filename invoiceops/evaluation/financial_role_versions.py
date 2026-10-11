"""Three frozen-source strategies, two explicit annotation bases, private traces only."""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.financial_role_challenge import (
    Metrics,
    load_annotation,
    metrics,
)
from invoiceops.evaluation.financial_role_challenge import (
    Outcomes as RoleOutcomes,
)
from invoiceops.evaluation.financial_role_challenge import (
    score as role_score,
)
from invoiceops.evaluation.financial_summary_guard import (
    CachedSourceExtractor,
    Outcomes,
    merge,
)
from invoiceops.evaluation.financial_summary_guard import (
    score as legacy_score,
)
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
from invoiceops.extraction.financial_role_guard import FinancialRoleGuardExtractor
from invoiceops.extraction.financial_summary_guard import FinancialSummaryGuardExtractor
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime
from invoiceops.schemas.extraction import ExtractionStatus


class LegacyMetrics(Aggregate):
    counts: Outcomes
    emitted_total_precision: Rate
    correct_total_recall: Rate


class Strategy(Aggregate):
    legacy_total_labels: LegacyMetrics | None
    independent_role_labels: Metrics | None
    false_abstentions: Rate | None
    added_abstentions_vs_baseline: Rate
    new_abstentions_vs_03: Rate
    recovered_totals_vs_03: Rate
    unchanged_non_total: Rate


class VersionReport(Aggregate):
    metric_version: Literal["financial-role-three-version-v1"] | None = None
    cohort: Literal["observed_development", "synthetic_contract"]
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    baseline_version: Literal["deterministic-baseline@0.2.0"] = "deterministic-baseline@0.2.0"
    guard_03_version: Literal["deterministic-financial-summary-guard@0.3.0"] = (
        "deterministic-financial-summary-guard@0.3.0"
    )
    guard_04_version: Literal["deterministic-financial-summary-guard@0.4.0"] = (
        "deterministic-financial-summary-guard@0.4.0"
    )
    documents: int
    pages: int
    ocr_documents: int
    ocr_version: str | None = Field(pattern=r"^[0-9]+(?:\.[0-9]+)+$")
    baseline: Strategy
    guard_03: Strategy
    guard_04: Strategy
    limitations: Literal["development-only-no-model-no-PO-matching"] = (
        "development-only-no-model-no-PO-matching"
    )


def run_versions(
    manifest: Path,
    output: Path,
    diagnostics: Path,
    *,
    repository: Path,
    cohort: Literal["observed_development", "synthetic_contract"],
) -> VersionReport:
    output = fresh_public(output, repository)
    diagnostics = private_path(diagnostics, repository)
    if diagnostics.exists():
        raise FileExistsError("Private output must be fresh")
    manifest = private_path(manifest, repository)
    prepared, fingerprints = [], []
    for example in ManifestAdapter().load(manifest).examples:
        if example.split != "development":
            raise ValueError("Frozen regression corpus must be development data")
        body = member(manifest.parent, example.document_path, repository).read_bytes()
        annotation, roles = load_annotation(
            member(manifest.parent, example.ground_truth_path, repository).read_bytes()
        )
        if (roles is not None) != (cohort == "synthetic_contract"):
            raise ValueError("Frozen cohort annotation basis mismatch")
        if roles and roles.provenance != "synthetic_contract":
            raise ValueError("Synthetic cohort requires synthetic contract provenance")
        canonical = (roles or annotation).model_dump_json().encode()
        fingerprints.append(bytes.fromhex(_length_delimited_hash([body, canonical])))
        prepared.append((example, body, annotation, roles, canonical))
    role_parts: list[list[RoleOutcomes]] = [[], [], []]
    legacy_parts: list[list[Outcomes]] = [[], [], []]
    false = [0, 0, 0]
    added, new, recovered, unchanged = [0, 0, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]
    eligible = emitted_base = emitted_03 = abstained_03 = pages = ocr = 0
    cases = []
    with quiet_extraction():
        runtime = inspect_ocr_runtime()
        for example, body, annotation, roles, canonical in prepared:
            observed = ObservedTextExtractor(runtime)
            base = EvaluationRunner(text_extractor=observed)._evaluate(
                example, body, annotation.legacy_truth(), canonical
            )
            labels = [
                getattr(annotation, n)
                for n in ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")
            ] + [
                getattr(r, n)
                for r in annotation.line_items.rows
                for n in ("description", "quantity", "unit_price", "line_total")
            ]
            if roles:
                labels += [f for r in roles.roles() for f in (r.amount, r.printed_label)]
            if observed.page_count is not None and any(
                b.page >= observed.page_count for f in labels for b in f.evidence
            ):
                raise ValueError("Annotation page outside source")
            results = [base] + [
                EvaluationRunner(
                    text_extractor=CachedSourceExtractor(observed.document),
                    invoice_extractor=engine,
                )._evaluate(example, body, annotation.legacy_truth(), canonical)
                if observed.document
                else base
                for engine in (FinancialSummaryGuardExtractor(), FinancialRoleGuardExtractor())
            ]
            invoices = [r.prediction.invoice for r in results]
            emitted = [bool(i and i.total.status == ExtractionStatus.EXTRACTED) for i in invoices]
            abstained = [
                bool(i and i.total.status in (ExtractionStatus.AMBIGUOUS, ExtractionStatus.MISSING))
                for i in invoices
            ]
            emitted_base += int(emitted[0])
            emitted_03 += int(emitted[1])
            abstained_03 += int(abstained[1])
            source_correct = role_score(
                roles, invoices[0], observed.document
            ).source_supported_correct
            eligible += source_correct
            for index, invoice in enumerate(invoices):
                if roles:
                    role_parts[index].append(role_score(roles, invoice, observed.document))
                else:
                    legacy_parts[index].append(legacy_score(annotation, invoice, observed.document))
                false[index] += source_correct * int(abstained[index])
                added[index] += int(emitted[0] and abstained[index])
                new[index] += int(emitted[1] and abstained[index])
                recovered[index] += int(abstained[1] and emitted[index])
                baseline = invoices[0]
                unchanged[index] += int(
                    invoice is not None
                    and baseline is not None
                    and invoice.model_dump(exclude={"total"})
                    == baseline.model_dump(exclude={"total"})
                )
            pages += observed.page_count or 0
            ocr += int(observed.ocr_pages > 0)
            cases.append(
                dict(
                    document_id=example.document_id,
                    results=[r.model_dump(mode="json") for r in results],
                )
            )
    strategies = []
    for index in range(3):
        legacy = None
        if legacy_parts[index]:
            counts = merge(legacy_parts[index])
            legacy = LegacyMetrics(
                counts=counts,
                emitted_total_precision=ratio(
                    counts.correct, counts.correct + counts.wrong + counts.false_on_absent
                ),
                correct_total_recall=ratio(counts.correct, counts.present),
            )
        strategies.append(
            Strategy(
                legacy_total_labels=legacy,
                independent_role_labels=metrics(role_parts[index]) if role_parts[index] else None,
                false_abstentions=ratio(false[index], eligible)
                if cohort == "synthetic_contract"
                else None,
                added_abstentions_vs_baseline=ratio(added[index], emitted_base),
                new_abstentions_vs_03=ratio(new[index], emitted_03),
                recovered_totals_vs_03=ratio(recovered[index], abstained_03),
                unchanged_non_total=ratio(unchanged[index], len(prepared)),
            )
        )
    revision, state = source_state(repository)
    report = VersionReport(
        metric_version="financial-role-three-version-v1",
        cohort=cohort,
        corpus_fingerprint=_length_delimited_hash(sorted(fingerprints)),
        source_revision=revision,
        source_state=state,
        documents=len(prepared),
        pages=pages,
        ocr_documents=ocr,
        ocr_version=(
            m.group(1)
            if runtime.version and (m := re.fullmatch(r"tesseract v?([0-9.]+)", runtime.version))
            else None
        ),
        baseline=strategies[0],
        guard_03=strategies[1],
        guard_04=strategies[2],
    )
    payload = report.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    diagnostics.mkdir(parents=True, exist_ok=False)
    (diagnostics / "cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8"
    )
    (output / "report.json").write_text(payload, encoding="utf-8")
    (output / "report.md").write_text(
        "# Three-version financial-role regression\n\n"
        "Same native source tokens for all three frozen strategies. Both corpora are observed "
        "development regressions, not independent validation. Synthetic labels were authored "
        "before predictions. Legacy total labels are not reinterpreted as gross/payable roles; "
        "their false-abstention metric is unavailable. Legacy location-supported role errors "
        "are the subtotal-evidence subset, not a comprehensive financial-role score.\n\n"
        "Correct/wrong/ambiguous/missing/failures use present target labels. Value precision = "
        "correct / (correct + wrong + emissions on absent); recall = correct / present. "
        "Role errors require independent printed-role and bound amount evidence; unresolved "
        "evidence is separate. False abstentions use source-supported correct baseline gross "
        "totals. Added/new abstentions use emitted baseline/0.3 totals respectively; recoveries "
        "use missing/ambiguous 0.3 totals. Extraction failures do not count as recovered or "
        "abstained invoices. All review gates are pre-PO checks, not MATCHED/payment decisions. "
        "Non-total equality includes evidence. Keep 0.4 opt-in.\n\n```json\n" + payload + "```\n",
        encoding="utf-8",
    )
    return report
