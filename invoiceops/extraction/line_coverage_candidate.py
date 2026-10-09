"""Opt-in two-column invoice table mode; frozen parsing remains untouched."""

from dataclasses import dataclass

from invoiceops.extraction.line_item_rules import (
    ParsedTableRow,
    _description_only,
    _is_footer,
    _is_ignored,
    _resolve_continuations,
    _row_text,
    is_probable_line_item,
    parse_table_row,
)
from invoiceops.extraction.normalization import parse_money
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.table_layout import (
    _HEADER_ALIASES,
    ColumnAnchor,
    ColumnRange,
    DetectedTableHeader,
    LineItemColumn,
    VisualRow,
    _best_anchor,
    _normalize_header_text,
    detect_table_header,
    infer_column_ranges,
    reconstruct_visual_rows,
)
from invoiceops.extraction.version import (
    LINE_COVERAGE_EXTRACTOR_NAME,
    LINE_COVERAGE_EXTRACTOR_VERSION,
)
from invoiceops.schemas.extraction import DocumentText, Invoice, InvoiceLine

_MAX_WRAP_GAP = 0.03
_PROSE_ENDINGS = (
    "thank you",
    "please remit",
    "remit to",
    "payment terms",
)
type CoverageHeader = DetectedTableHeader | TwoColumnHeader


@dataclass(frozen=True)
class TwoColumnHeader:
    page: int
    row: VisualRow
    columns: tuple[ColumnAnchor, ColumnAnchor]


def _unique_anchor(row: VisualRow, column: LineItemColumn) -> ColumnAnchor | None:
    selected = _best_anchor(row, column)
    if selected is None:
        return None
    for start in range(len(row.words)):
        for size in range(1, min(3, len(row.words) - start) + 1):
            words = row.words[start : start + size]
            if (
                _normalize_header_text(" ".join(word.text for word in words))
                not in _HEADER_ALIASES[column]
            ):
                continue
            if any(
                word.bbox.x0 < selected.bbox.x0 - 1e-6 or word.bbox.x1 > selected.bbox.x1 + 1e-6
                for word in words
            ):
                return None
    return selected


def detect_candidate_header(row: VisualRow) -> CoverageHeader | None:
    frozen = detect_table_header(row)
    if frozen is not None:
        return frozen
    if any(char.isdigit() for word in row.words for char in word.text):
        return None
    if any(
        _best_anchor(row, column) is not None
        for column in (
            LineItemColumn.QUANTITY,
            LineItemColumn.UNIT_PRICE,
        )
    ):
        return None
    description = _unique_anchor(row, LineItemColumn.DESCRIPTION)
    total = _unique_anchor(row, LineItemColumn.LINE_TOTAL)
    if description is None or total is None or total.bbox.x0 - description.bbox.x1 < 0.02:
        return None
    # Every non-separator token must be in one of the two explicit labels.
    if any(
        _normalize_header_text(word.text)
        and not any(
            anchor.bbox.x0 <= word.bbox.x0 + 1e-6 and anchor.bbox.x1 >= word.bbox.x1 - 1e-6
            for anchor in (description, total)
        )
        for word in row.words
    ):
        return None
    return TwoColumnHeader(row.page, row, (description, total))


def candidate_column_ranges(header: CoverageHeader) -> list[ColumnRange]:
    if isinstance(header, DetectedTableHeader):
        return infer_column_ranges(header)
    left, right = header.columns
    boundary = (left.center_x + right.center_x) / 2
    return [
        ColumnRange(column=LineItemColumn.DESCRIPTION, x0=0.0, x1=boundary),
        ColumnRange(column=LineItemColumn.LINE_TOTAL, x0=boundary, x1=1.0),
    ]


def candidate_row_is_probable(row: ParsedTableRow, ranges: list[ColumnRange]) -> bool:
    if len(ranges) == 2:
        # Never concatenate multiple independently numeric cells into one monetary value.
        numeric_words = sum(parse_money(word.text) is not None for word in row.line_total_words)
        if numeric_words != 1:
            return False
    return is_probable_line_item(row)


def candidate_is_footer(row: VisualRow, ranges: list[ColumnRange]) -> bool:
    if _is_footer(row):
        return True
    if len(ranges) != 2:
        return False
    text = _row_text(row).lower().strip()
    if _is_ignored(row) or text.startswith(_PROSE_ENDINGS):
        return True
    if text == "total" or text.startswith(("total:", "total ")):
        remainder = text[5:].lstrip(" :")
        return not remainder or parse_money(remainder) is not None
    return False


def _resolve_two_column_section(
    rows: list[ParsedTableRow], ranges: list[ColumnRange]
) -> list[InvoiceLine]:
    valid = [index for index, row in enumerate(rows) if candidate_row_is_probable(row, ranges)]
    filtered = []
    for index, row in enumerate(rows):
        if index in valid:
            filtered.append(row)
            continue
        if not _description_only(row):
            continue
        gaps = [
            (row.y0 - rows[item].y1 if item < index else rows[item].y0 - row.y1) for item in valid
        ]
        if not gaps:
            continue
        closest = min(gaps)
        if 0 <= closest <= _MAX_WRAP_GAP and sum(abs(gap - closest) < 1e-6 for gap in gaps) == 1:
            filtered.append(row)
    return _resolve_continuations(filtered)


def _flush_section(
    section: list[ParsedTableRow],
    ranges: list[ColumnRange] | None,
) -> list[InvoiceLine]:
    if ranges is None:
        return []
    if len(ranges) == 2:
        return _resolve_two_column_section(section, ranges)
    return _resolve_continuations(section)


def extract_candidate_line_items(document: DocumentText) -> list[InvoiceLine]:
    visual_rows = reconstruct_visual_rows(document)
    items = []
    for page in sorted({row.page for row in visual_rows}):
        section: list[ParsedTableRow] = []
        ranges: list[ColumnRange] | None = None

        for row in (row for row in visual_rows if row.page == page):
            header = detect_candidate_header(row)
            if isinstance(header, TwoColumnHeader) and ranges is not None and len(ranges) >= 3:
                header = None
            if header is not None:
                items.extend(_flush_section(section, ranges))
                ranges = candidate_column_ranges(header)
                section = []
                continue
            if ranges is None:
                continue
            if candidate_is_footer(row, ranges):
                items.extend(_flush_section(section, ranges))
                ranges = None
                section = []
                continue
            if _is_ignored(row):
                continue
            section.append(parse_table_row(row, ranges))
        items.extend(_flush_section(section, ranges))
    return items


class LineCoverageInvoiceExtractor(DeterministicInvoiceExtractor):
    name = LINE_COVERAGE_EXTRACTOR_NAME
    version = LINE_COVERAGE_EXTRACTOR_VERSION

    def extract(self, document: DocumentText) -> Invoice:
        frozen = super().extract(document)
        return frozen.model_copy(update={"line_items": extract_candidate_line_items(document)})
