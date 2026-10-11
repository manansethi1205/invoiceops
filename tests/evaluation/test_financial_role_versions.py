import json
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.financial_role_versions import VersionReport, run_versions
from invoiceops.evaluation.real_input import ObservedTextExtractor
from invoiceops.extraction.ocr_runtime import OcrRuntimeInfo
from tests.evaluation.financial_role_fixtures import challenge_fixture, write_contract_corpus


def test_three_versions_share_native_source_and_protect_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    manifest = write_contract_corpus(tmp_path, include_scan=False)
    output = tmp_path / "evals/reports/real-input/versions"
    private = tmp_path / "work/real-invoice-private/traces"
    report = run_versions(
        manifest, output, private, repository=tmp_path, cohort="synthetic_contract"
    )
    assert report.documents == report.pages == 11
    assert report.metric_version == "financial-role-three-version-v1"
    for strategy in (report.baseline, report.guard_03, report.guard_04):
        assert strategy.independent_role_labels is not None
        assert strategy.independent_role_labels.counts.present == 10
        assert strategy.unchanged_non_total.numerator == 11
    latest = report.guard_04.independent_role_labels
    assert latest is not None
    assert latest.counts.wrong == latest.counts.source_supported_role_errors == 0
    assert report.guard_04.false_abstentions is not None
    assert report.guard_04.false_abstentions.numerator == 0
    assert report.guard_04.false_abstentions.denominator == 6
    content = (output / "report.json").read_text()
    for secret in (str(tmp_path), "contract-0", "100.00", "source-0", "document_id"):
        assert secret not in content
    with pytest.raises(FileExistsError):
        run_versions(manifest, output, private, repository=tmp_path, cohort="synthetic_contract")
    with pytest.raises(FileExistsError):
        run_versions(
            manifest,
            output.parent / "fresh",
            private,
            repository=tmp_path,
            cohort="synthetic_contract",
        )
    payload = json.loads(content)
    payload.pop("metric_version")
    for name in ("ocr_attempted_documents", "ocr_failed_documents", "ocr_failure_rate"):
        payload.pop(name)
    assert VersionReport.model_validate(payload).metric_version is None
    assert VersionReport.model_validate(payload).ocr_failed_documents is None
    payload["private_notes"] = "secret"
    with pytest.raises(ValidationError):
        VersionReport.model_validate(payload)


def authorized_contract(repo: Path) -> tuple[Path, Path]:
    """Synthetic contract simulation, never a claim of human-reviewed real results."""
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("work/\n")
    manifest = write_contract_corpus(repo, include_scan=False)
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    reference = manifest.with_name("observed.jsonl")
    reference.write_text(json.dumps(records[-1]) + "\n")
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records[:-1]))
    for record in records[:-1]:
        path = manifest.parent / record["ground_truth_path"]
        label = json.loads(path.read_text())
        label["provenance"] = "human"
        path.write_text(json.dumps(label))
    return manifest, reference


def test_new_authorized_contract_uses_one_source_and_separate_denominators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, reference = authorized_contract(tmp_path)
    calls = 0
    original = ObservedTextExtractor.extract

    def extract(self: ObservedTextExtractor, body: bytes, content_type: str) -> Any:
        nonlocal calls
        calls += 1
        return original(self, body, content_type)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(ObservedTextExtractor, "extract", extract)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    output = tmp_path / "evals/reports/real-input/new"
    private = tmp_path / "work/real-invoice-private/new"
    report = run_versions(
        manifest,
        output,
        private,
        repository=tmp_path,
        cohort="new_authorized_challenge",
        observed_manifest=reference,
    )
    assert calls == report.documents == report.pages == 10
    assert report.ocr_attempted_documents == report.ocr_failed_documents == 0
    assert report.ocr_failure_rate is not None
    assert report.ocr_failure_rate.denominator == 0
    assert report.cohort == "new_authorized_challenge"
    for strategy in (report.baseline, report.guard_03, report.guard_04):
        labels = strategy.independent_role_labels
        assert labels is not None and strategy.legacy_total_labels is None
        counts = labels.counts
        assert counts.present == 9
        assert (
            counts.correct
            + counts.wrong
            + counts.ambiguous
            + counts.missing
            + counts.failed_present
        ) == 9
        assert strategy.false_abstentions is not None
        assert strategy.false_abstentions.denominator == 6
        assert strategy.unchanged_non_total.numerator == 10
        assert labels.correct_total_recall.denominator == 9
        assert labels.emitted_total_precision.denominator == (
            counts.correct + counts.wrong + counts.emitted_on_absent
        )
    for filename in ("report.json", "report.md"):
        public = (output / filename).read_text()
        for secret in (str(tmp_path), "contract-0", "100.00", "source-0", "document_id"):
            assert secret not in public
    with pytest.raises(FileExistsError):
        run_versions(
            manifest,
            output,
            private,
            repository=tmp_path,
            cohort="new_authorized_challenge",
            observed_manifest=reference,
        )


@pytest.mark.parametrize(
    "defect",
    [
        "no_reference",
        "overlap",
        "duplicate_bytes",
        "duplicate_id",
        "synthetic_labels",
        "unfrozen",
        "legacy",
        "traversal",
    ],
)
def test_new_authorized_preflight_refuses_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, defect: str
) -> None:
    manifest, observed = authorized_contract(tmp_path)
    reference: Path | None = observed
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    label_path = manifest.parent / records[0]["ground_truth_path"]
    labels = json.loads(label_path.read_text())
    if defect == "no_reference":
        reference = None
    elif defect == "overlap":
        reference = manifest
    elif defect == "duplicate_bytes":
        (manifest.parent / records[1]["document_path"]).write_bytes(
            (manifest.parent / records[0]["document_path"]).read_bytes()
        )
    elif defect == "duplicate_id":
        records[1]["document_id"] = records[0]["document_id"]
    elif defect == "synthetic_labels":
        labels["provenance"] = "synthetic_contract"
    elif defect == "unfrozen":
        labels["labelled_without_predictions"] = False
    elif defect == "legacy":
        labels = dict(annotation_version="human-invoice-v1", provenance="human")
    else:
        records[0]["document_path"] = "../escape.pdf"
    label_path.write_text(json.dumps(labels))
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Source extraction must not start")

    monkeypatch.setattr(ObservedTextExtractor, "extract", forbidden)
    output = tmp_path / "evals/reports/real-input/refused"
    with pytest.raises(ValueError):
        run_versions(
            manifest,
            output,
            tmp_path / "work/real-invoice-private/refused",
            repository=tmp_path,
            cohort="new_authorized_challenge",
            observed_manifest=reference,
        )
    assert not output.exists()


def test_new_authorized_ocr_failure_has_attempt_denominator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, reference = authorized_contract(tmp_path)
    record = json.loads(manifest.read_text().splitlines()[0])
    body, _ = challenge_fixture(
        [(50, 200, "Total", "gross_invoice_total"), (200, 200, "100.00", None)], scan=True
    )
    (manifest.parent / record["document_path"]).write_bytes(body)
    record["content_type"] = "image/png"
    manifest.write_text(json.dumps(record) + "\n")
    monkeypatch.setattr(
        "invoiceops.evaluation.financial_role_versions.inspect_ocr_runtime",
        lambda: OcrRuntimeInfo(available=False),
    )
    report = run_versions(
        manifest,
        tmp_path / "evals/reports/real-input/ocr",
        tmp_path / "work/real-invoice-private/ocr",
        repository=tmp_path,
        cohort="new_authorized_challenge",
        observed_manifest=reference,
    )
    assert report.ocr_attempted_documents == report.ocr_failed_documents == 1
    assert report.ocr_documents == 0
    assert report.ocr_failure_rate is not None
    assert report.ocr_failure_rate.numerator == report.ocr_failure_rate.denominator == 1
    for strategy in (report.baseline, report.guard_03, report.guard_04):
        assert strategy.independent_role_labels is not None
        assert strategy.independent_role_labels.counts.failed_present == 1
        assert strategy.false_abstentions is not None
        assert strategy.false_abstentions.denominator == 0


def test_cli_forwards_explicit_new_challenge_reference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from scripts import run_financial_role_versions as cli

    captured: dict[str, Any] = {}

    def fake(*args: Any, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(documents=10)

    monkeypatch.setattr(cli, "run_versions", fake)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_financial_role_versions.py",
            "--cohort",
            "new_authorized_challenge",
            "--manifest",
            "private-manifest",
            "--observed-manifest",
            "private-reference",
            "--output-dir",
            "fresh-output",
            "--private-diagnostics",
            "private-output",
        ],
    )
    cli.main()
    assert captured["cohort"] == "new_authorized_challenge"
    assert captured["observed_manifest"] == Path("private-reference")
    assert capsys.readouterr().out == (
        "Aggregate comparison complete: 10 documents; no provider calls.\n"
    )


def test_runtime_and_cli_imports_cannot_load_evaluation_or_provider() -> None:
    for module in (
        "invoiceops.extraction.financial_role_guard",
        "scripts.run_financial_role_versions",
    ):
        code = f"""
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'openai','httpx','httpcore','requests'}}:
            raise AssertionError('External SDK forbidden')
        runtime = {module!r}.startswith('invoiceops.extraction')
        if runtime and fullname.startswith('invoiceops.evaluation'):
            raise AssertionError('Runtime annotation dependency forbidden')
sys.meta_path.insert(0, Guard())
import {module}
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
