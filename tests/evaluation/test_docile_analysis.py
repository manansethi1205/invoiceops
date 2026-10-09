from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from invoiceops.evaluation.docile_analysis import field_counts, localization_counts, status_counts
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.schemas.extraction import TextSource
from scripts.analyze_docile_failures import reserve_output
from tests.unit.test_header_rules import document_from_lines


def test_analysis_never_overwrites_existing_output(tmp_path: Path) -> None:
    path = tmp_path / "report"
    reserve_output(path)
    sentinel = path / "report.json"
    sentinel.write_text("frozen", encoding="utf-8")
    with pytest.raises(FileExistsError):
        reserve_output(path)
    assert sentinel.read_text(encoding="utf-8") == "frozen"


def test_omitted_task_counts_real_annotation_denominator_without_exporting_text() -> None:
    result = SimpleNamespace(task_to_docid_to_matching={})
    documents = [
        SimpleNamespace(
            annotation=SimpleNamespace(
                fields=[
                    SimpleNamespace(fieldtype="document_id", text="private sentinel"),
                    SimpleNamespace(fieldtype="date_issue", text="private sentinel"),
                    SimpleNamespace(fieldtype="document_id", text="private sentinel"),
                ]
            )
        )
    ]
    counts = field_counts(result, documents, "kile", {"document_id", "date_issue"})
    assert counts["document_id"]["FN"] == 2
    assert counts["date_issue"]["FN"] == 1
    assert counts["document_id"]["TP"] == counts["document_id"]["FP"] == 0
    assert "private sentinel" not in str(counts)
    assert localization_counts(result, "kile", {"document_id"}) == {}


def test_present_task_uses_official_field_counts() -> None:
    class Result:
        task_to_docid_to_matching: dict[str, Any] = {"kile": {}}

        def get_metrics(self, task: str, fieldtype: str) -> dict[str, int]:
            assert task == "kile" and fieldtype == "document_id"
            return {"TP": 1, "FP": 2, "FN": 3}

    assert field_counts(Result(), [], "kile", {"document_id"}) == {
        "document_id": {"TP": 1, "FP": 2, "FN": 3}
    }


def test_status_counts_export_only_field_names_and_counts() -> None:
    document = document_from_lines([(0, "Invoice No: SYN-42", TextSource.OCR)])
    invoice = DeterministicInvoiceExtractor().extract(document)
    counts = status_counts([invoice])
    assert counts["document_id"] == {"extracted": 1}
    assert counts["date_issue"] == {"missing": 1}
    assert "SYN-42" not in str(counts)


@pytest.mark.parametrize("existing_name", ["report.json", "report.md"])
def test_report_writer_rejects_existing_artifact_before_writing(
    tmp_path: Path, existing_name: str
) -> None:
    from invoiceops.evaluation.docile_report import (
        DocileAggregateReport,
        DocileModeMetrics,
        write_docile_aggregate_report,
    )

    mode = dict(
        document_count=100,
        supported_subset_kile_f1=0.0,
        supported_subset_lir_f1=0.0,
        official_full_kile_f1=0.0,
        official_full_lir_f1=0.0,
        official_full_kile_ap=0.0,
        official_full_lir_ap=0.0,
    )
    report = DocileAggregateReport(
        extractor_name="synthetic",
        extractor_version="test",
        sample_manifest_sha256="a" * 64,
        modes=[
            DocileModeMetrics(mode="end_to_end", **mode),
            DocileModeMetrics(mode="precomputed_ocr", **mode),
        ],
    )
    sentinel = tmp_path / existing_name
    sentinel.write_text("frozen", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_docile_aggregate_report(tmp_path, report)
    assert sentinel.read_text(encoding="utf-8") == "frozen"
    assert sorted(path.name for path in tmp_path.iterdir()) == [existing_name]


def test_geometric_overlap_is_separate_from_official_matches() -> None:
    class Box:
        def __init__(self, overlaps: bool) -> None:
            self.overlaps = overlaps

        def intersects(self, other: object) -> bool:
            return self.overlaps

    prediction = SimpleNamespace(fieldtype="document_id", page=0, bbox=Box(True))
    annotation = SimpleNamespace(fieldtype="document_id", page=0, bbox=Box(True))
    unsupported = SimpleNamespace(fieldtype="vendor_name", page=0, bbox=Box(True))
    matching = SimpleNamespace(false_positives=[prediction, unsupported], annotations=[annotation])
    result = SimpleNamespace(task_to_docid_to_matching={"kile": {"synthetic": matching}})
    assert localization_counts(result, "kile", {"document_id"}) == {
        "unmatched_with_same_class_overlap": 1
    }
    annotation.page = 1
    assert localization_counts(result, "kile", {"document_id"}) == {
        "unmatched_without_same_class_overlap": 1
    }


def test_report_writer_creates_a_fresh_pair_and_refuses_a_repeat(tmp_path: Path) -> None:
    import json

    from invoiceops.evaluation.docile_report import (
        DocileAggregateReport,
        write_docile_aggregate_report,
    )
    from tests.evaluation.test_docile_report import _metrics

    report = DocileAggregateReport(
        extractor_name="synthetic",
        extractor_version="test",
        sample_manifest_sha256="a" * 64,
        modes=[_metrics("end_to_end"), _metrics("precomputed_ocr")],
    )
    path = tmp_path / "fresh"
    write_docile_aggregate_report(path, report)
    before = {file.name: file.read_bytes() for file in path.iterdir()}
    assert json.loads(before["report.json"])["extractor_name"] == "synthetic"
    assert b"End-to-end" in before["report.md"]
    with pytest.raises(FileExistsError):
        write_docile_aggregate_report(path, report)
    assert before == {file.name: file.read_bytes() for file in path.iterdir()}
