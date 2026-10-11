import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest

from invoiceops.evaluation.hybrid_live import LiveReport
from invoiceops.evaluation.hybrid_local import run_hybrid_local_manifest
from invoiceops.evaluation.live_budget import BudgetedVisionProvider
from invoiceops.evaluation.live_corpus import load_corpus, write_corpus
from invoiceops.extraction.ocr_runtime import OcrRuntimeInfo, OcrRuntimeUnavailableError
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from scripts import run_hybrid_evaluation as cli


@pytest.fixture(autouse=True)
def forbid_external_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Local evaluation must not initialize or call a network provider")

    for target, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (httpx, "Client"),
        (openai, "OpenAI"),
        (BudgetedVisionProvider, "__init__"),
        (cli, "get_settings"),
        (cli, "verified_profile"),
    ):
        monkeypatch.setattr(target, name, forbidden)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path, Path]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    root = tmp_path / "work" / "hybrid-live-synthetic" / "corpus-run2"
    # Non-default seed proves this evaluates the supplied manifest, not replay fixtures.
    write_corpus(root, tmp_path, 12345)
    return tmp_path, root / "manifest.json", tmp_path / "evals/reports/hybrid/local"


def test_local_cli_evaluates_verified_manifest_without_external_calls(
    corpus: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repository, manifest, output = corpus
    monkeypatch.setattr(cli, "__file__", str(repository / "scripts/runner.py"))

    def forbid_ocr(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Synthetic scan fixture must not invoke OCR")

    monkeypatch.setattr(DocumentTextExtractor, "_extract_ocr_words", forbid_ocr)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--mode",
            "synthetic-local",
            "--manifest",
            str(manifest),
            "--max-documents",
            "16",
            "--max-pages",
            "17",
            "--allow-holdout",
            "--local-source-mode",
            "synthetic-scan-tokens",
            "--output-dir",
            str(output),
        ],
    )
    cli.main()
    report = LiveReport.model_validate_json((output / "report.json").read_bytes())
    assert report.metric_version == "synthetic-source-safety-v2"
    cases, fingerprint, seed = load_corpus(manifest, repository, "all")
    assert report.mode == "synthetic-local"
    assert report.local_provider_version == "label-guided-stub-v1"
    assert report.corpus_fingerprint == fingerprint and report.corpus_seed == seed == 12345
    assert report.documents == len(cases) == 16 and report.pages == 17
    assert report.source_input_mode == "synthetic-scan-tokens"
    assert report.ocr_documents == 0 and report.synthetic_scan_documents == 2
    assert report.ocr_engine is None and report.ocr_engine_version is None
    for kind, docs, rows in (("pdf", 14, 28), ("png", 2, 4)):
        for mode in (
            report.metrics_by_input_type[kind].deterministic,
            report.metrics_by_input_type[kind].hybrid,
        ):
            assert mode.documents == docs and mode.labelled_lines == rows
    for mode_name in ("deterministic", "hybrid"):
        for name in ("line_tp", "line_fp", "line_fn", "review_documents", "matched_documents"):
            assert sum(
                getattr(getattr(part, mode_name), name)
                for part in report.metrics_by_input_type.values()
            ) == getattr(getattr(report.metrics["all"], mode_name), name)
    for name in (
        "candidate_rows",
        "associated_rows",
        "unscorable_promotions",
        "unscorable_associations",
    ):
        assert sum(
            getattr(part.safety, name) for part in report.metrics_by_input_type.values()
        ) == getattr(report.metrics["all"].safety, name)
    assert report.price_assumptions is None
    assert report.usage.requests > 0  # Local fixtures do run; external calls are forbidden above.
    assert report.usage.input_tokens == report.usage.output_tokens == report.usage.total_tokens == 0
    assert report.usage.estimated_total_cost_usd == report.usage.spending_limit_usd == "0"
    for split, docs, rows in (("all", 16, 32), ("development", 8, 16), ("unseen", 8, 16)):
        metrics = report.metrics[split]
        for mode in (metrics.deterministic, metrics.hybrid):
            assert mode.documents == docs and mode.labelled_lines == rows
            assert mode.line_tp + mode.line_fn == rows
            assert mode.line_tp + mode.line_fp == mode.predicted_lines
            assert all(rate.denominator == docs for rate in mode.header_exact_match.values())
        assert metrics.safety.false_cross_row_promotions.numerator == 0
        assert metrics.safety.false_financial_promotions.numerator == 0
    stdout = capsys.readouterr().out
    payload = (output / "report.json").read_text() + (output / "report.md").read_text()
    for private in (str(repository), "case-001", "Alpha item", cases[0].truth.invoice_number):
        assert private not in payload and private not in stdout
    assert "no model" in stdout
    saved = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_hybrid_local_manifest(
            manifest,
            repository=repository,
            output_dir=output,
            max_documents=16,
            max_pages=17,
            allow_holdout=True,
            source_mode="synthetic-scan-tokens",
        )
    assert (output / "report.json").read_bytes() == saved


def test_legacy_report_does_not_infer_current_metric_version(
    corpus: tuple[Path, Path, Path],
) -> None:
    repository, manifest, output = corpus
    fresh = run_hybrid_local_manifest(
        manifest,
        repository=repository,
        output_dir=output,
        max_documents=8,
        max_pages=8,
        partition="development",
        source_mode="native",
    )
    payload = json.loads((output / "report.json").read_text())
    assert fresh.metric_version == payload["metric_version"] == "synthetic-source-safety-v2"
    legacy = dict(payload)
    for name in ("metric_version", "ocr_engine", "ocr_engine_version", "metrics_by_input_type"):
        legacy.pop(name)
    loaded = LiveReport.model_validate(legacy)
    assert loaded.metric_version is None
    assert loaded.metrics_by_input_type == {}
    assert loaded.ocr_engine is None and loaded.ocr_engine_version is None
    assert all(loaded.model_dump(mode="json")[name] == value for name, value in legacy.items())
    assert json.loads(loaded.model_dump_json())["metric_version"] is None
    legacy["metric_version"] = None
    assert LiveReport.model_validate(legacy).metric_version is None
    assert LiveReport.model_validate(payload).metric_version == "synthetic-source-safety-v2"


def test_native_local_refuses_unavailable_ocr_without_scan_substitution(
    corpus: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, manifest, output = corpus
    monkeypatch.setattr(
        "invoiceops.evaluation.hybrid_live.inspect_ocr_runtime",
        lambda: OcrRuntimeInfo(available=False),
    )
    with pytest.raises(OcrRuntimeUnavailableError):
        run_hybrid_local_manifest(
            manifest,
            repository=repository,
            output_dir=output,
            max_documents=16,
            max_pages=17,
            allow_holdout=True,
            source_mode="native",
        )
    assert not output.exists()


@pytest.mark.parametrize("option", ["--allow-live", "--model", "--max-spend-usd"])
def test_local_cli_refuses_live_options(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    args = ["runner", "--mode", "synthetic-local", option]
    if option != "--allow-live":
        args.append("1")
    monkeypatch.setattr(sys, "argv", args)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize(
    "failure", ["tampered", "document-limit", "page-limit", "reserved", "unsafe"]
)
def test_local_keeps_corpus_and_output_guards(
    corpus: tuple[Path, Path, Path],
    failure: str,
) -> None:
    repository, manifest, output = corpus
    if failure == "tampered":
        payload = json.loads(manifest.read_text())
        payload["seed"] = 999
        manifest.write_text(json.dumps(payload), encoding="utf-8")
    if failure == "unsafe":
        output = repository / "outputs/not-an-aggregate-report"
    with pytest.raises(ValueError):
        run_hybrid_local_manifest(
            manifest,
            repository=repository,
            output_dir=output,
            max_documents=15 if failure == "document-limit" else 16,
            max_pages=16 if failure == "page-limit" else 17,
            allow_holdout=failure != "reserved",
            source_mode="synthetic-scan-tokens",
        )
    assert not output.exists()
