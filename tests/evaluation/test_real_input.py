import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import openai
import pymupdf
import pytest
from pydantic import ValidationError

from invoiceops.evaluation.human_annotations import HumanField
from invoiceops.evaluation.real_input import (
    RealInputReport,
    evidence_supported,
    run_private_benchmark,
)
from invoiceops.evaluation.schemas import GroundTruthInvoice
from invoiceops.extraction.errors import OcrUnavailableError
from invoiceops.extraction.ocr_runtime import OcrRuntimeInfo
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)
from scripts import run_private_invoice_evaluation as cli
from tests.synthetic_documents import generated_incomplete_invoice_pdf, generated_invoice_pdf


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("External calls and provider initialization forbidden")

    for target, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket, "create_connection"),
        (httpx, "Client"),
        (openai, "OpenAI"),
        (openai, "AsyncOpenAI"),
    ):
        monkeypatch.setattr(target, name, forbidden)
    monkeypatch.setattr(
        "invoiceops.evaluation.real_input.inspect_ocr_runtime",
        lambda: OcrRuntimeInfo(available=False),
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def annotation(body: bytes) -> dict[str, Any]:
    # Synthetic human-style labels: fixed printed values, never extraction predictions.
    values = {
        "invoice_number": ("SYN-12345", "SYN-12345"),
        "invoice_date": ("2026-09-19", "19/09/2026"),
        "currency": ("INR", "INR"),
        "subtotal": ("1200", "1,200.00"),
        "tax": ("216", "216.00"),
        "total": ("1416", "1,416.00"),
    }
    payload: dict[str, Any] = {"annotation_version": "human-invoice-v1", "provenance": "human"}
    with pymupdf.open(stream=body, filetype="pdf") as pdf:
        page = pdf[0]
        for name, (value, text) in values.items():
            box = page.search_for(text)[0]
            payload[name] = {
                "status": "present",
                "value": value,
                "evidence": [
                    {
                        "page": 0,
                        "bbox": {
                            "x0": box.x0 / 612,
                            "x1": box.x1 / 612,
                            "y0": box.y0 / 792,
                            "y1": box.y1 / 792,
                        },
                    }
                ],
            }
        rows = []
        for description, qty, price, total in (
            ("Industrial Filter", "2", "500.00", "1,000.00"),
            ("Mounting Bracket", "4", "50.00", "200.00"),
        ):
            row = {}
            for name, text in zip(
                ("description", "quantity", "unit_price", "line_total"),
                (description, qty, price, total),
                strict=True,
            ):
                box = page.search_for(text)[0]
                row[name] = {
                    "status": "present",
                    "value": text.replace(",", ""),
                    "evidence": [
                        {
                            "page": 0,
                            "bbox": {
                                "x0": box.x0 / 612,
                                "x1": box.x1 / 612,
                                "y0": box.y0 / 792,
                                "y1": box.y1 / 792,
                            },
                        }
                    ],
                }
            rows.append(row)
        payload["line_items"] = {"status": "present", "rows": rows}
    return payload


def dataset(
    repository: Path,
    *,
    bodies: list[bytes] | None = None,
    types: list[str] | None = None,
    labels: list[dict[str, Any]] | None = None,
) -> Path:
    bodies = bodies or [generated_invoice_pdf()]
    types = types or ["application/pdf"] * len(bodies)
    labels = labels or [annotation(generated_invoice_pdf()) for _ in bodies]
    root = repository / "work/real-invoice-private/corpus"
    root.mkdir(parents=True)
    records = []
    for index, (body, kind, label) in enumerate(zip(bodies, types, labels, strict=True)):
        (root / f"private-file-{index}").write_bytes(body)
        (root / f"private-label-{index}.json").write_text(json.dumps(label), encoding="utf-8")
        records.append(
            {
                "document_id": f"private-id-{index}",
                "split": "development",
                "document_path": f"private-file-{index}",
                "content_type": kind,
                "ground_truth_path": f"private-label-{index}.json",
                "tags": {"private-tag": "never publish"},
            }
        )
    manifest = root / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return manifest


def run(repository: Path, manifest: Path, leaf: str = "run", **kwargs: Any) -> RealInputReport:
    return run_private_benchmark(
        manifest, repository / f"evals/reports/real-input/{leaf}", repository=repository, **kwargs
    )


@pytest.mark.parametrize(
    "field",
    [
        {"status": "present", "value": "x"},
        {"status": "present", "evidence": []},
        {"status": "absent", "value": "x"},
        {"status": "not_annotated", "value": "x"},
        {
            "status": "present",
            "value": " ",
            "evidence": [{"page": 0, "bbox": {"x0": 0.1, "x1": 0.2, "y0": 0.1, "y1": 0.2}}],
        },
    ],
)
def test_human_label_contract_refuses_inconsistent_labels(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        HumanField[str].model_validate(field)


def test_real_pipeline_accounting_privacy_and_legacy(repository: Path) -> None:
    manifest = dataset(repository)
    report = run(repository, manifest)
    assert report.metric_version == "real-input-human-v1" and report.definitions is not None
    all_counts = report.slices["all"]
    assert all_counts.attempted_documents == all_counts.schema_validity.numerator == 1
    assert all_counts.failed_documents == 0 and all_counts.total_known_pages == 1
    assert (all_counts.line_tp, all_counts.line_fp, all_counts.line_fn) == (2, 0, 0)
    assert all_counts.line_f1.rate == 1 and all_counts.line_scored_documents == 1
    assert all_counts.headers["total"].value_exact == 1
    assert report.slices["embedded_only"].attempted_documents == 1
    assert report.slices["scan_or_ocr"].attempted_documents == 0
    payload = report.model_dump()
    payload.pop("metric_version")
    assert RealInputReport.model_validate(payload).metric_version is None
    assert GroundTruthInvoice.model_validate({}).total is None
    public = "".join(p.read_text() for p in (repository / "evals/reports/real-input/run").iterdir())
    for private in (
        str(repository),
        "private-id",
        "private-file",
        "private-label",
        "SYN-12345",
        "Industrial Filter",
        "1,416.00",
        "never publish",
        "private-tag",
    ):
        assert private not in public
    with pytest.raises(ValidationError):
        RealInputReport.model_validate({**report.model_dump(), "document_id": "unsafe"})
    saved = (repository / "evals/reports/real-input/run/report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run(repository, manifest)
    assert (repository / "evals/reports/real-input/run/report.json").read_bytes() == saved


def test_absent_unannotated_and_failed_denominators(repository: Path) -> None:
    known = annotation(generated_invoice_pdf())
    absent = {
        "annotation_version": "human-invoice-v1",
        "provenance": "human",
        "tax": {"status": "absent"},
        "line_items": {"status": "absent"},
    }
    unlabelled = {"annotation_version": "human-invoice-v1", "provenance": "human"}
    manifest = dataset(
        repository,
        bodies=[
            generated_invoice_pdf(),
            generated_incomplete_invoice_pdf(),
            b"broken",
            generated_invoice_pdf(),
        ],
        labels=[known, absent, absent, unlabelled],
    )
    report = run(repository, manifest)
    metric = report.slices["all"]
    tax = metric.headers["tax"]
    assert (tax.present, tax.absent, tax.not_annotated) == (1, 2, 1)
    assert tax.present_exact_accuracy.denominator == 1
    assert tax.absent_abstention_accuracy.numerator == 1
    assert tax.absent_abstention_accuracy.denominator == 2
    assert tax.absent_failed_documents == 1
    assert tax.annotated_exact_accuracy.denominator == 3
    assert metric.line_scored_documents == 3 and metric.line_unannotated_documents == 1
    assert metric.failed_documents == 1 and metric.schema_validity.denominator == 4
    assert metric.unknown_page_documents == 1 and metric.latency_documents == 4
    assert (
        sum(
            report.slices[s].attempted_documents
            for s in ("scan_or_ocr", "embedded_only", "unknown")
        )
        == 4
    )


def test_explicit_absence_false_extraction_and_partial_rows(repository: Path) -> None:
    label = annotation(generated_invoice_pdf())
    label["tax"] = {"status": "absent"}
    label["line_items"]["rows"][0]["quantity"] = {"status": "not_annotated"}
    report = run(repository, dataset(repository, labels=[label])).slices["all"]
    assert report.headers["tax"].false_extractions_on_absent == 1
    assert report.headers["tax"].absent_abstentions == 0
    assert report.line_partial_documents == 1 and report.line_scored_documents == 0
    assert report.line_f1.denominator == 0 and report.line_f1.rate is None


@pytest.mark.parametrize("backend_failure", [False, True])
def test_actual_image_bytes_ocr_failure_counts(
    repository: Path, monkeypatch: pytest.MonkeyPatch, backend_failure: bool
) -> None:
    with pymupdf.open(stream=generated_invoice_pdf(), filetype="pdf") as pdf:
        pix = pdf[0].get_pixmap()
        images = [pix.tobytes("png"), pix.tobytes("jpeg")]
    if backend_failure:
        monkeypatch.setattr(
            "invoiceops.evaluation.real_input.inspect_ocr_runtime",
            lambda: OcrRuntimeInfo(available=True, version="tesseract 5.5.0"),
        )

        def fail(page: Any) -> Any:
            raise OcrUnavailableError("private decoder payload")

        monkeypatch.setattr(DocumentTextExtractor, "_extract_ocr_words", staticmethod(fail))
    report = run(
        repository, dataset(repository, bodies=images, types=["image/png", "image/jpeg"])
    ).slices["all"]
    assert report.ocr_attempted_documents == report.ocr_failed_documents == 2
    assert report.ocr_completed_documents == report.ocr_completed_pages == 0
    assert report.failed_documents == 2 and report.errors == {"ocr_unavailable": 2}
    assert report.known_page_documents == 2 and report.total_known_pages == 2
    assert report.headers["total"].present_exact_accuracy.denominator == 2
    assert report.line_fn == 4 and report.input_types == {"pdf": 0, "png": 1, "jpeg": 1}


def test_malformed_formats_remain_in_denominators(repository: Path) -> None:
    report = run(
        repository,
        dataset(
            repository, bodies=[b"broken"] * 3, types=["application/pdf", "image/png", "image/jpeg"]
        ),
    )
    metric = report.slices["all"]
    assert metric.failed_documents == metric.unknown_page_documents == 3
    assert metric.errors == {"unreadable_document": 3}
    assert metric.line_fn == 6 and metric.line_tp == metric.line_fp == 0
    assert metric.line_recall.denominator == 6 and metric.line_recall.rate == 0


@pytest.mark.parametrize("damage", ["quote", "page", "box", "missing"])
def test_evidence_must_match_human_location_and_source_tokens(damage: str) -> None:
    box = BoundingBox(x0=0.1, x1=0.2, y0=0.1, y1=0.2)
    evidence = EvidenceSpan(page=0, bbox=box, text="SYN", source=TextSource.EMBEDDED)
    label = HumanField[object].model_validate(
        {"status": "present", "value": "SYN", "evidence": [{"page": 0, "bbox": box}]}
    )
    document = DocumentText(
        used_ocr=False,
        pages=[
            PageText(
                page=0,
                width=100,
                height=100,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=[
                    WordToken(
                        text="SYN",
                        page=0,
                        bbox=box,
                        source=TextSource.EMBEDDED,
                        block_number=0,
                        line_number=0,
                        word_number=0,
                    )
                ],
            )
        ],
    )
    field = ExtractedField[object](
        value="SYN", status=ExtractionStatus.EXTRACTED, evidence=[evidence]
    )
    assert evidence_supported(field, label, document)
    bad = field.model_copy(deep=True)
    if damage == "missing":
        bad.evidence = []
    elif damage == "quote":
        bad.evidence[0].text = "unrelated"
    elif damage == "page":
        bad.evidence[0].page = 1
    else:
        bad.evidence[0].bbox = BoundingBox(x0=0.5, x1=0.6, y0=0.5, y1=0.6)
    assert not evidence_supported(bad, label, document)


def test_missing_predicted_evidence_is_schema_failure(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = DeterministicInvoiceExtractor.extract

    def broken(self: DeterministicInvoiceExtractor, document: DocumentText) -> Any:
        invoice = original(self, document)
        invoice.total.evidence = []
        return invoice

    monkeypatch.setattr(DeterministicInvoiceExtractor, "extract", broken)
    metric = run(repository, dataset(repository)).slices["all"]
    assert metric.errors == {"schema_validation_failed": 1}
    assert metric.schema_validity.numerator == 0 and metric.line_fn == 2


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "traversal",
        "windows",
        "missing",
        "label-page",
        "oracle",
        "legacy-label",
        "holdout",
    ],
)
def test_manifest_and_annotation_preflight_refusals(repository: Path, damage: str) -> None:
    manifest = dataset(repository)
    records = [json.loads(line) for line in manifest.read_text().splitlines()]
    if damage == "duplicate":
        records *= 2
    elif damage == "traversal":
        records[0]["document_path"] = "../private-file-0"
    elif damage == "windows":
        records[0]["document_path"] = "C:\\private.pdf"
    elif damage == "missing":
        records[0]["document_path"] = "missing.pdf"
    elif damage == "holdout":
        records[0]["split"] = "holdout"
    else:
        path = manifest.parent / "private-label-0.json"
        label = json.loads(path.read_text())
        if damage == "label-page":
            label["total"]["evidence"][0]["page"] = 8
        elif damage == "oracle":
            label["provenance"] = "oracle"
        else:
            label = {"total": "1416"}
        path.write_text(json.dumps(label), encoding="utf-8")
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        run(repository, manifest)
    assert not (repository / "evals/reports/real-input/run").exists()


def test_fingerprint_reproducible_and_sensitive_to_human_labels(repository: Path) -> None:
    manifest = dataset(repository)
    first = run(repository, manifest, "first")
    record = json.loads(manifest.read_text())
    record["document_id"] = "renamed private ID"
    manifest.write_text(json.dumps(record), encoding="utf-8")
    assert run(repository, manifest, "second").corpus_fingerprint == first.corpus_fingerprint
    label_path = manifest.parent / "private-label-0.json"
    label = json.loads(label_path.read_text())
    label["total"]["value"] = "9999"
    label_path.write_text(json.dumps(label), encoding="utf-8")
    assert run(repository, manifest, "third").corpus_fingerprint != first.corpus_fingerprint


def test_private_diagnostics_are_opt_in_and_guarded(repository: Path) -> None:
    manifest = dataset(repository)
    private = repository / "work/real-invoice-private/diagnostics/run"
    run(repository, manifest, private_diagnostics=private)
    assert "private-id-0" in (private / "cases.jsonl").read_text()
    assert "human_annotation" in (private / "cases.jsonl").read_text()
    with pytest.raises(FileExistsError):
        run(repository, manifest, "second", private_diagnostics=private)
    with pytest.raises(ValueError):
        run(repository, manifest, "third", private_diagnostics=repository / "evals/private")
    with pytest.raises(ValueError):
        run_private_benchmark(manifest, repository / "work/public", repository=repository)


def test_links_and_tracked_private_assets_refused(repository: Path) -> None:
    manifest = dataset(repository)
    source = manifest.parent / "private-file-0"
    original = source.with_name("original.pdf")
    source.rename(original)
    try:
        source.symlink_to(original)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(ValueError):
        run(repository, manifest)
    source.unlink()
    original.rename(source)
    subprocess.run(["git", "add", "-f", str(source)], cwd=repository, check=True)
    with pytest.raises(ValueError):
        run(repository, manifest)


def test_cli_success_and_failure_logs_are_opaque(
    repository: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = dataset(repository)
    monkeypatch.setattr(cli, "__file__", str(repository / "scripts/runner.py"))
    args = [
        "runner",
        "--manifest",
        str(manifest),
        "--output-dir",
        str(repository / "evals/reports/real-input/run"),
    ]
    monkeypatch.setattr(sys, "argv", args)
    cli.main()
    assert "1 attempts" in capsys.readouterr().out
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert str(repository) not in output.err and "private-id" not in output.err


def test_cli_import_graph_has_no_external_provider() -> None:
    code = """
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'httpx', 'httpcore'}:
            raise AssertionError('External SDK import forbidden')
sys.meta_path.insert(0, Guard())
import scripts.run_private_invoice_evaluation
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_incorrect_human_evidence_does_not_get_supported_credit(repository: Path) -> None:
    label = annotation(generated_invoice_pdf())
    label["total"]["evidence"][0]["bbox"] = {"x0": 0.01, "x1": 0.02, "y0": 0.01, "y1": 0.02}
    result = run(repository, dataset(repository, labels=[label])).slices["all"]
    assert result.headers["total"].value_exact == 1
    assert result.headers["total"].supported_exact == 0


def test_image_bytes_use_existing_ocr_hook_with_no_label_token_substitution(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def empty_ocr(page: Any) -> list[object]:
        calls.append(page.number)
        return []  # Backend test double, deliberately supplies no labelled values.

    monkeypatch.setattr(
        "invoiceops.evaluation.real_input.inspect_ocr_runtime",
        lambda: OcrRuntimeInfo(available=True, version="tesseract 5.5.0"),
    )
    monkeypatch.setattr(DocumentTextExtractor, "_extract_ocr_words", staticmethod(empty_ocr))
    with pymupdf.open(stream=generated_invoice_pdf(), filetype="pdf") as pdf:
        pix = pdf[0].get_pixmap()
        images = [pix.tobytes("png"), pix.tobytes("jpeg")]
    result = run(repository, dataset(repository, bodies=images, types=["image/png", "image/jpeg"]))
    assert len(calls) == 2
    assert result.slices["scan_or_ocr"].attempted_documents == 2
    assert result.slices["all"].ocr_completed_documents == 2
    assert result.slices["all"].ocr_completed_pages == 2
    assert result.slices["all"].ocr_failed_documents == 0
    assert result.slices["all"].headers["invoice_number"].value_exact == 0
    assert result.slices["all"].schema_validity.numerator == 2


def test_mixed_pdf_ocr_failure_keeps_total_page_denominator(
    repository: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pymupdf.open(stream=generated_invoice_pdf(), filetype="pdf") as pdf:
        pdf.new_page()
        body = pdf.tobytes()
    result = run(repository, dataset(repository, bodies=[body]))
    assert result.slices["scan_or_ocr"].attempted_documents == 1
    assert result.slices["all"].ocr_failed_documents == 1
    assert result.slices["all"].total_known_pages == 2


def test_tracked_and_nonignored_private_assets_refused(repository: Path) -> None:
    manifest = dataset(repository)
    source = manifest.parent / "private-file-0"
    subprocess.run(["git", "add", "-f", str(source)], cwd=repository, check=True)
    with pytest.raises(ValueError):
        run(repository, manifest)
    subprocess.run(
        ["git", "rm", "--cached", "-f", str(source)],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    (repository / ".gitignore").write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        run(repository, manifest)
