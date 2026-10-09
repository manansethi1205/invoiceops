import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from invoiceops.evaluation.line_coverage import (
    annotated_stage_counts,
    micro_counts,
    trace_line_parser,
)
from invoiceops.extraction.line_item_rules import extract_line_items
from invoiceops.schemas.extraction import TextSource
from scripts.analyze_docile_line_coverage import private_cache_root
from tests.unit.test_line_item_rules import document, table_page


def annotation(page: int, line: int, x0: float, y0: float, kind: str = "line_item_description"):
    return SimpleNamespace(
        page=page,
        line_item_id=line,
        fieldtype=kind,
        text="PRIVATE_SENTINEL",
        bbox=SimpleNamespace(left=x0, top=y0, right=x0 + 0.3, bottom=y0 + 0.025),
    )


def test_trace_distinguishes_header_rejections_and_emissions() -> None:
    doc = document(
        table_page(
            0,
            [
                (0.25, "Synthetic Part", "2", "10.00", "20.00"),
                (0.30, "wrapped phrase", "", "", ""),
                (0.35, "Rejected Part", "2x", "bad", ""),
                (0.40, "Terms and Conditions", "", "", "100.00"),
                (0.45, "Grand Total", "", "", "20.00"),
                (0.50, "Outside Part", "1", "10.00", "10.00"),
            ],
        )
    )
    items = extract_line_items(doc)
    trace = trace_line_parser(doc, items)
    assert trace.counts["rows_header"] == 1
    assert trace.counts["rows_probable_item"] == trace.counts["emitted_lines"] == 1
    assert trace.counts["rows_description_only"] == 1
    assert trace.counts["rows_no_numeric_support"] == 1
    assert trace.counts["rows_ignored"] == 1
    assert trace.counts["rows_footer"] == 1
    assert trace.counts["rows_before_header"] == 1
    assert sum(value for key, value in trace.counts.items() if key.startswith("rows_")) == len(
        trace.rows
    )


def test_annotation_partition_does_not_equate_wrapping_with_a_failure() -> None:
    doc = document(
        table_page(
            0,
            [
                (0.25, "Synthetic Part", "2", "10.00", "20.00"),
                (0.30, "wrapped phrase", "", "", ""),
            ],
        )
    )
    trace = trace_line_parser(doc, extract_line_items(doc))
    counts = annotated_stage_counts(
        trace,
        [
            annotation(0, 1, 0.08, 0.25),
            annotation(0, 1, 0.08, 0.30),
            annotation(0, 1, 0.53, 0.25, "line_item_quantity"),
        ],
    )
    assert counts["annotated_line_page_groups"] == 1
    assert counts["line_groups_multiple_visual_token_rows"] == 1
    assert counts["line_groups_stage_probable_item_row"] == 1
    assert counts["line_groups_numeric_cells_on_multiple_rows"] == 0


def test_no_header_and_missing_ocr_tokens_are_distinct() -> None:
    doc = document(
        table_page(0, [(0.25, "Synthetic Part", "2", "10", "20")], aliases=("", "", "", ""))
    )
    trace = trace_line_parser(doc, [])
    counts = annotated_stage_counts(
        trace,
        [
            annotation(0, 1, 0.08, 0.25),
            annotation(0, 2, 0.08, 0.70),
        ],
    )
    assert counts["line_groups_stage_header_not_detected_on_page"] == 1
    assert counts["line_groups_stage_visual_tokens_missing"] == 1
    assert sum(value for key, value in counts.items() if key.startswith("line_groups_stage_")) == 2


def test_repeated_multipage_headers_have_independent_sections() -> None:
    doc = document(
        table_page(0, [(0.25, "First Part", "1", "10", "10")]),
        table_page(1, [(0.25, "Second Part", "1", "10", "10")], source=TextSource.OCR),
    )
    trace = trace_line_parser(doc, extract_line_items(doc))
    assert trace.counts["pages_with_detected_header"] == 2
    assert trace.counts["rows_header"] == trace.counts["emitted_lines"] == 2


def test_aggregate_export_has_no_source_text_or_ids() -> None:
    doc = document(table_page(0, [(0.25, "PRIVATE_SENTINEL", "1", "10", "10")]))
    trace = trace_line_parser(doc, extract_line_items(doc))
    counts = annotated_stage_counts(trace, [annotation(0, 123456789, 0.08, 0.25)])
    exported = json.dumps(
        {
            "counts": trace.counts,
            "annotations": counts,
            "signatures": trace.rejected_header_signatures,
            "probes": trace.probes,
        }
    )
    assert "PRIVATE_SENTINEL" not in exported
    assert "123456789" not in exported


def test_supported_micro_denominators_and_empty_predictions() -> None:
    result = micro_counts(
        {"description": {"TP": 2, "FP": 1, "FN": 8}, "quantity": {"TP": 3, "FP": 0, "FN": 7}}
    )
    assert result == {
        "TP": 5,
        "FP": 1,
        "FN": 15,
        "predictions": 6,
        "annotations": 20,
        "precision": 5 / 6,
        "recall": 0.25,
        "f1": 10 / 26,
    }
    assert micro_counts({"description": {"TP": 0, "FP": 0, "FN": 10}})["recall"] == 0


def test_private_cache_rejects_host_filesystems(monkeypatch, tmp_path: Path) -> None:
    import scripts.analyze_docile_line_coverage as runner

    mounts = tmp_path / "mounts"
    mounts.write_text("host /private-cache ext4 rw 0 0\n", encoding="utf-8")
    monkeypatch.setattr(
        runner, "Path", lambda value: mounts if value == "/proc/mounts" else Path(value)
    )
    with pytest.raises(RuntimeError, match="tmpfs"):
        private_cache_root()
