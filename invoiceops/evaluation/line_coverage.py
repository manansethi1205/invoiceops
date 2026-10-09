"""Aggregate-only stage diagnostics for the frozen invoice line parser."""

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from invoiceops.extraction.line_item_rules import (
    ParsedTableRow,
    _description_only,
    _is_footer,
    _is_ignored,
    is_probable_line_item,
    parse_table_row,
)
from invoiceops.extraction.table_layout import (
    ColumnRange,
    LineItemColumn,
    VisualRow,
    _best_anchor,
    detect_table_header,
    infer_column_ranges,
    reconstruct_visual_rows,
)
from invoiceops.schemas.extraction import DocumentText, InvoiceLine

type HeaderDetector = Callable[[VisualRow], Any]


@dataclass
class LineCoverageTrace:
    """Ephemeral row locations; only counters may be exported."""

    counts: Counter[str]
    row_stages: list[str]
    rows: list[VisualRow]
    rejected_header_signatures: Counter[str]
    probes: Counter[str]
    page_has_header: set[int]


def trace_line_parser(
    document: DocumentText,
    emitted: Sequence[InvoiceLine],
    detector: HeaderDetector = detect_table_header,
    range_builder: Callable[[Any], list[ColumnRange]] = infer_column_ranges,
    row_validator: Callable[[ParsedTableRow, list[ColumnRange]], bool] | None = None,
    footer_detector: Callable[[VisualRow, list[ColumnRange]], bool] | None = None,
) -> LineCoverageTrace:
    rows = reconstruct_visual_rows(document)
    counts: Counter[str] = Counter(
        {
            "documents": 1,
            "pages": len(document.pages),
            "pages_with_words": sum(bool(page.words) for page in document.pages),
            "word_tokens": sum(len(page.words) for page in document.pages),
            "visual_rows": len(rows),
            "emitted_lines": len(emitted),
            "documents_with_emitted_lines": int(bool(emitted)),
            "emitted_quantity_fields": sum(line.quantity.value is not None for line in emitted),
        }
    )
    stages = []
    signatures: Counter[str] = Counter()
    probes: Counter[str] = Counter()
    page_has_header: set[int] = set()
    ranges = None
    previous_page = None
    for row in rows:
        if row.page != previous_page:
            ranges = None
            previous_page = row.page
        header = detector(row)
        if (
            header is not None
            and len(header.columns) == 2
            and ranges is not None
            and len(ranges) >= 3
        ):
            header = None
        if header is not None:
            ranges = range_builder(header)
            page_has_header.add(row.page)
            stage = "header"
        elif ranges is None:
            stage = "before_header"
        elif footer_detector(row, ranges) if footer_detector else _is_footer(row):
            stage = "footer"
            ranges = None
        elif _is_ignored(row):
            stage = "ignored"
        else:
            parsed = parse_table_row(row, ranges)
            if row_validator(parsed, ranges) if row_validator else is_probable_line_item(parsed):
                stage = "probable_item"
            elif _description_only(parsed):
                stage = "description_only"
            elif not parsed.description_words:
                stage = "missing_description"
            else:
                stage = "no_numeric_support"
        stages.append(stage)
        counts["rows_" + stage] += 1
        if header is None and not any(char.isdigit() for word in row.words for char in word.text):
            columns = {column for column in LineItemColumn if _best_anchor(row, column) is not None}
            if LineItemColumn.DESCRIPTION in columns:
                signatures["+".join(sorted(column.value for column in columns))] += 1
                normalized = {word.text.lower().strip(" .:") for word in row.words}
                if "total" in normalized and LineItemColumn.LINE_TOTAL not in columns:
                    probes["description_with_unrecognized_bare_total"] += 1
                    if LineItemColumn.QUANTITY in columns:
                        probes["description_quantity_unrecognized_bare_total"] += 1
                    if LineItemColumn.UNIT_PRICE in columns:
                        probes["description_unit_price_unrecognized_bare_total"] += 1
                if "price" in normalized and LineItemColumn.UNIT_PRICE not in columns:
                    probes["description_with_unrecognized_bare_price"] += 1
                if columns == {LineItemColumn.DESCRIPTION, LineItemColumn.LINE_TOTAL}:
                    probes["description_line_total_without_optional_numeric"] += 1
    counts["pages_with_detected_header"] = len(page_has_header)
    return LineCoverageTrace(counts, stages, rows, signatures, probes, page_has_header)


def _word_in_field(word: Any, field: Any) -> bool:
    x = (word.bbox.x0 + word.bbox.x1) / 2
    y = (word.bbox.y0 + word.bbox.y1) / 2
    return bool(
        word.page == field.page
        and field.bbox.left <= x <= field.bbox.right
        and field.bbox.top <= y <= field.bbox.bottom
    )


def annotated_stage_counts(
    trace: LineCoverageTrace,
    fields: Sequence[Any],
) -> Counter[str]:
    """Partition annotated line/page groups by the earliest observed parser bottleneck.

    Token-center containment is diagnostic only; official PCC/LIR matches are scored separately.
    Multiple rows can be legitimate wrapping and are not automatically a construction failure.
    """
    grouped: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for field in fields:
        if field.line_item_id is not None:
            grouped[(field.page, field.line_item_id)].append(field)
    counts: Counter[str] = Counter({"annotated_line_page_groups": len(grouped)})
    for (page, _), group in grouped.items():
        group_top = min(field.bbox.top for field in group)
        group_bottom = max(field.bbox.bottom for field in group)
        token_rows = {
            index
            for index, row in enumerate(trace.rows)
            if row.page == page
            and row.y1 >= group_top
            and row.y0 <= group_bottom
            and any(_word_in_field(word, field) for field in group for word in row.words)
        }
        numeric_rows = {
            index
            for index in token_rows
            if any(
                field.fieldtype != "line_item_description" and _word_in_field(word, field)
                for field in group
                for word in trace.rows[index].words
            )
        }
        counts[
            "line_groups_"
            + (
                "no_visual_token_rows"
                if not token_rows
                else "one_visual_token_row"
                if len(token_rows) == 1
                else "multiple_visual_token_rows"
            )
        ] += 1
        if len(numeric_rows) > 1:
            counts["line_groups_numeric_cells_on_multiple_rows"] += 1
        if not token_rows:
            stage = "visual_tokens_missing"
        elif page not in trace.page_has_header:
            stage = "header_not_detected_on_page"
        else:
            row_stages = {trace.row_stages[index] for index in (numeric_rows or token_rows)}
            if "probable_item" in row_stages:
                stage = "probable_item_row"
            elif row_stages == {"before_header"}:
                stage = "outside_active_section"
            elif "footer" in row_stages or "ignored" in row_stages:
                stage = "footer_or_ignored"
            elif "header" in row_stages:
                stage = "misclassified_as_header"
            else:
                stage = "body_row_rejected"
        counts["line_groups_stage_" + stage] += 1
    return counts


def micro_counts(fields: dict[str, dict[str, float | int]]) -> dict[str, float | int]:
    tp = sum(int(value["TP"]) for value in fields.values())
    fp = sum(int(value["FP"]) for value in fields.values())
    fn = sum(int(value["FN"]) for value in fields.values())
    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "predictions": tp + fp,
        "annotations": tp + fn,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
    }
