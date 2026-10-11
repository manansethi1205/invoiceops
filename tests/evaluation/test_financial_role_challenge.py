import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.financial_role_challenge import (
    ChallengeReport,
    RoleAnnotation,
    load_annotation,
    metrics,
    run_challenge,
    score,
)
from invoiceops.extraction.financial_summary_guard import FinancialSummaryGuardExtractor
from invoiceops.extraction.ocr_runtime import OcrRuntimeInfo
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from tests.evaluation.financial_role_fixtures import challenge_fixture, write_contract_corpus


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def test_native_contract_pair_privacy_denominators_and_fresh_paths(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("No external calls")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    manifest = write_contract_corpus(repository, include_scan=False)
    output = repository / "evals/reports/real-input/challenge"
    private = repository / "work/real-invoice-private/traces"
    report = run_challenge(
        manifest, output, private, repository=repository, cohort="synthetic_contract"
    )
    assert report.documents == report.pages == report.unchanged_non_total_documents == 11
    assert report.metric_version == "financial-role-challenge-v1"
    for strategy in (report.baseline, report.guard):
        c = strategy.counts
        assert c.present == c.correct + c.wrong + c.missing + c.ambiguous + c.failed_present == 10
        assert strategy.emitted_total_precision.denominator == c.correct + c.wrong
        assert strategy.correct_total_recall.denominator == 10
        assert c.emitted == (
            c.source_supported_correct
            + c.source_supported_role_errors
            + c.unresolved_emitted_evidence
        )
    assert report.baseline.counts.correct == 6
    assert report.guard.counts.correct == 5
    assert report.guard.counts.wrong == 1
    assert report.guard.counts.ambiguous == 3
    assert report.false_abstentions.numerator == 1
    assert report.false_abstentions.denominator == report.baseline.counts.source_supported_correct
    assert report.guard.counts.source_supported_role_errors >= 1
    public = (output / "report.json").read_text(encoding="utf-8")
    for secret in (str(repository), "contract-0", "100.00", "Payable", "source-0", "evidence"):
        # Aggregate evidence COUNTERS are public; case evidence/text is not.
        if secret != "evidence":
            assert secret not in public
    payload = json.loads(public)
    payload.pop("metric_version")
    assert ChallengeReport.model_validate(payload).metric_version is None
    payload["document_id"] = "private"
    with pytest.raises(ValidationError):
        ChallengeReport.model_validate(payload)
    frozen = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_challenge(manifest, output, private, repository=repository, cohort="synthetic_contract")
    assert (output / "report.json").read_bytes() == frozen
    with pytest.raises(FileExistsError):
        run_challenge(
            manifest,
            output.parent / "fresh",
            private,
            repository=repository,
            cohort="synthetic_contract",
        )
    with pytest.raises(ValueError):
        run_challenge(
            manifest,
            repository / "outside",
            private.parent / "fresh",
            repository=repository,
            cohort="synthetic_contract",
        )


def test_legacy_and_independent_annotation_contract() -> None:
    old = dict(annotation_version="human-invoice-v1", provenance="human")
    annotation, roles = load_annotation(json.dumps(old).encode())
    assert roles is None and annotation.total.status == "not_annotated"
    assert score(roles, None, None).unannotated == 1
    _, label = challenge_fixture(
        [(50, 200, "Total", "gross_invoice_total"), (200, 200, "100.00", None)]
    )
    label["labelled_without_predictions"] = False
    with pytest.raises(ValidationError):
        RoleAnnotation.model_validate(label)
    label["labelled_without_predictions"] = True
    label["gross_invoice_total"].pop("printed_label")
    with pytest.raises(ValidationError):
        RoleAnnotation.model_validate(label)


def test_equal_payable_value_is_not_gross_evidence_and_unknown_is_excluded() -> None:
    body, label = challenge_fixture(
        [
            (50, 200, "Total", "payable_balance"),
            (200, 200, "100.00", None),
            (50, 260, "Gross amount", "gross_invoice_total"),
            (200, 260, "100.00", None),
        ]
    )
    source = DocumentTextExtractor().extract(body, "application/pdf")
    invoice = DeterministicInvoiceExtractor().extract(source)
    result = score(RoleAnnotation.model_validate(label), invoice, source)
    assert result.correct == 1  # Numeric equality is explicitly a separate metric.
    assert result.source_supported_correct == 0
    assert result.source_supported_role_errors == 1
    label.pop("gross_invoice_total")
    result = score(RoleAnnotation.model_validate(label), invoice, source)
    m = metrics([result])
    assert m.correct_total_recall.denominator == m.emitted_total_precision.denominator == 0
    assert result.emitted_unannotated == result.unresolved_emitted_evidence == 1
    assert result.source_supported_role_errors == 0


def test_absence_bad_evidence_and_failures_reconcile() -> None:
    body, label = challenge_fixture(
        [(50, 200, "Total", "gross_invoice_total"), (200, 200, "100.00", None)]
    )
    source = DocumentTextExtractor().extract(body, "application/pdf")
    invoice = FinancialSummaryGuardExtractor().extract(source)
    label["gross_invoice_total"]["amount"]["evidence"][0]["bbox"] = dict(
        x0=0, x1=0.01, y0=0, y1=0.01
    )
    r = score(RoleAnnotation.model_validate(label), invoice, source)
    assert r.correct == r.unresolved_emitted_evidence == 1
    assert r.source_supported_correct == 0
    failed = score(RoleAnnotation.model_validate(label), None, None)
    assert metrics([r, failed]).correct_total_recall.denominator == 2
    label["gross_invoice_total"] = dict(
        amount=dict(status="absent"), printed_label=dict(status="absent")
    )
    r = score(RoleAnnotation.model_validate(label), invoice, source)
    assert r.absent == r.emitted_on_absent == 1
    assert metrics([r]).correct_total_recall.denominator == 0
    assert metrics([r]).emitted_total_precision.denominator == 1


def test_cli_import_excludes_provider_and_hybrid_sdk() -> None:
    code = """
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai','httpx','httpcore','requests'}:
            raise AssertionError('SDK forbidden')
sys.meta_path.insert(0, Guard())
import scripts.run_financial_role_challenge
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)


@pytest.mark.parametrize("defect", ["duplicate_id", "duplicate_source", "traversal", "wrong_page"])
def test_manifest_and_coordinate_refusals(repository: Path, defect: str) -> None:
    manifest = write_contract_corpus(repository, include_scan=False)
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    if defect == "duplicate_id":
        records[1]["document_id"] = records[0]["document_id"]
    elif defect == "duplicate_source":
        records[1]["document_path"] = records[0]["document_path"]
    elif defect == "traversal":
        records[0]["document_path"] = "../escape.pdf"
    else:
        path = manifest.parent / records[0]["ground_truth_path"]
        label = json.loads(path.read_text())
        label["gross_invoice_total"]["amount"]["evidence"][0]["page"] = 9
        label["gross_invoice_total"]["printed_label"]["evidence"][0]["page"] = 9
        path.write_text(json.dumps(label))
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records))
    output = repository / "evals/reports/real-input/refused"
    with pytest.raises(ValueError):
        run_challenge(
            manifest,
            output,
            repository / "work/real-invoice-private/refused",
            repository=repository,
            cohort="synthetic_contract",
        )
    assert not output.exists()


@pytest.mark.parametrize("scan", [False, True])
def test_malformed_source_and_unavailable_ocr_are_counted_failures(
    repository: Path, monkeypatch: pytest.MonkeyPatch, scan: bool
) -> None:
    manifest = write_contract_corpus(repository, include_scan=False)
    record = json.loads(manifest.read_text().splitlines()[0])
    if scan:
        body, _ = challenge_fixture(
            [(50, 200, "Total", "gross_invoice_total"), (200, 200, "100.00", None)], scan=True
        )
        record["content_type"] = "image/png"
    else:
        body = b"malformed PDF"
    (manifest.parent / record["document_path"]).write_bytes(body)
    manifest.write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(
        "invoiceops.evaluation.financial_role_challenge.inspect_ocr_runtime",
        lambda: OcrRuntimeInfo(available=False),
    )
    report = run_challenge(
        manifest,
        repository / "evals/reports/real-input/failures",
        repository / "work/real-invoice-private/failures",
        repository=repository,
        cohort="synthetic_contract",
    )
    assert report.failed_documents == report.documents == 1
    assert report.baseline.counts.failed_present == report.guard.counts.failed_present == 1
    assert report.false_abstentions.denominator == 0


def test_new_challenge_refuses_observed_sources(repository: Path) -> None:
    manifest = write_contract_corpus(repository, include_scan=False)
    for record in manifest.read_text().splitlines():
        path = manifest.parent / json.loads(record)["ground_truth_path"]
        label = json.loads(path.read_text())
        label["provenance"] = "human"
        path.write_text(json.dumps(label))
    output = repository / "evals/reports/real-input/new"
    for reference in (None, manifest):
        with pytest.raises(ValueError):
            run_challenge(
                manifest,
                output,
                repository / "work/real-invoice-private/new",
                repository=repository,
                cohort="new_authorized_challenge",
                observed_manifest=reference,
            )
    assert not output.exists()


def test_legacy_manifest_stays_role_unannotated(repository: Path) -> None:
    manifest = write_contract_corpus(repository, include_scan=False)
    record = json.loads(manifest.read_text().splitlines()[0])
    path = manifest.parent / record["ground_truth_path"]
    path.write_text(json.dumps(dict(annotation_version="human-invoice-v1", provenance="human")))
    manifest.write_text(json.dumps(record) + "\n")
    output = repository / "evals/reports/real-input/legacy"
    private = repository / "work/real-invoice-private/legacy"
    with pytest.raises(ValueError):
        run_challenge(manifest, output, private, repository=repository, cohort="synthetic_contract")
    report = run_challenge(
        manifest, output, private, repository=repository, cohort="observed_development"
    )
    assert report.baseline.counts.unannotated == report.guard.counts.unannotated == 1
    assert report.false_abstentions.denominator == 0


def test_accounting_refuses_inconsistent_counters() -> None:
    from invoiceops.evaluation.financial_role_challenge import Outcomes

    with pytest.raises(ValueError):
        metrics([Outcomes(documents=1, present=1, emitted=1)])
