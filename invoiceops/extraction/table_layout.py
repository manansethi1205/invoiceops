import re
from enum import StrEnum
from statistics import median

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.extraction.layout import union_bbox
from invoiceops.schemas.extraction import BoundingBox, DocumentText, WordToken


class VisualRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=0)
    y0: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    words: list[WordToken] = Field(min_length=1)


class LineItemColumn(StrEnum):
    DESCRIPTION = "description"
    QUANTITY = "quantity"
    UNIT_PRICE = "unit_price"
    LINE_TOTAL = "line_total"


class ColumnAnchor(BaseModel):
    model_config = ConfigDict(frozen=True)

    column: LineItemColumn
    bbox: BoundingBox
    center_x: float = Field(ge=0, le=1)
    matched_text: str


class DetectedTableHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=0)
    row: VisualRow
    columns: list[ColumnAnchor] = Field(min_length=3)
    score: int = Field(ge=5)


class ColumnRange(BaseModel):
    model_config = ConfigDict(frozen=True)

    column: LineItemColumn
    x0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)


_HEADER_ALIASES: dict[LineItemColumn, set[str]] = {
    LineItemColumn.DESCRIPTION: {
        "description",
        "item",
        "item description",
        "particulars",
        "product",
        "product description",
        "service",
        "details",
    },
    LineItemColumn.QUANTITY: {"qty", "quantity", "units", "unit qty"},
    LineItemColumn.UNIT_PRICE: {
        "unit price",
        "unit rate",
        "rate",
        "price/unit",
        "price each",
        "unit cost",
    },
    LineItemColumn.LINE_TOTAL: {
        "amount",
        "line total",
        "total amount",
        "net amount",
        "extended price",
        "value",
    },
}
_COLUMN_SCORES = {
    LineItemColumn.DESCRIPTION: 2,
    LineItemColumn.QUANTITY: 1,
    LineItemColumn.UNIT_PRICE: 1,
    LineItemColumn.LINE_TOTAL: 2,
}


def _vertical_center(word: WordToken) -> float:
    return (word.bbox.y0 + word.bbox.y1) / 2


def _substantial_vertical_overlap(word: WordToken, row_words: list[WordToken]) -> bool:
    row_y0 = min(item.bbox.y0 for item in row_words)
    row_y1 = max(item.bbox.y1 for item in row_words)
    overlap = max(0.0, min(word.bbox.y1, row_y1) - max(word.bbox.y0, row_y0))
    smaller_height = min(word.bbox.y1 - word.bbox.y0, row_y1 - row_y0)
    return smaller_height > 0 and overlap / smaller_height >= 0.5


def reconstruct_visual_rows(
    document: DocumentText,
    *,
    y_tolerance_factor: float = 0.6,
) -> list[VisualRow]:
    if y_tolerance_factor <= 0:
        raise ValueError("visual-row tolerance factor must be positive")

    rows: list[VisualRow] = []
    for page in sorted(document.pages, key=lambda item: item.page):
        if not page.words:
            continue
        heights = [word.bbox.y1 - word.bbox.y0 for word in page.words]
        tolerance = max(0.004, median(heights) * y_tolerance_factor)
        ordered_words = sorted(page.words, key=lambda word: (_vertical_center(word), word.bbox.x0))
        grouped: list[list[WordToken]] = []
        for word in ordered_words:
            if not grouped:
                grouped.append([word])
                continue
            current = grouped[-1]
            row_center = median(_vertical_center(item) for item in current)
            if (
                abs(_vertical_center(word) - row_center) <= tolerance
                or _substantial_vertical_overlap(word, current)
            ):
                current.append(word)
            else:
                grouped.append([word])

        for row_words in grouped:
            row_words.sort(key=lambda word: (word.bbox.x0, word.word_number))
            rows.append(
                VisualRow(
                    page=page.page,
                    y0=min(word.bbox.y0 for word in row_words),
                    y1=max(word.bbox.y1 for word in row_words),
                    words=row_words,
                )
            )
    return sorted(rows, key=lambda row: (row.page, row.y0, row.words[0].bbox.x0))


def _normalize_header_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9/]+", " ", value.lower()).split())


def _best_anchor(row: VisualRow, column: LineItemColumn) -> ColumnAnchor | None:
    aliases = _HEADER_ALIASES[column]
    best: tuple[int, int, ColumnAnchor] | None = None
    for start in range(len(row.words)):
        for size in range(1, min(3, len(row.words) - start) + 1):
            matched_words = row.words[start : start + size]
            matched_text = _normalize_header_text(" ".join(word.text for word in matched_words))
            if matched_text not in aliases:
                continue
            bbox = union_bbox(matched_words)
            anchor = ColumnAnchor(
                column=column,
                bbox=bbox,
                center_x=(bbox.x0 + bbox.x1) / 2,
                matched_text=" ".join(word.text for word in matched_words),
            )
            rank = (size, len(matched_text), anchor)
            if best is None or rank[:2] > best[:2]:
                best = rank
    return best[2] if best is not None else None


def detect_table_header(row: VisualRow) -> DetectedTableHeader | None:
    anchors = [
        anchor
        for column in LineItemColumn
        if (anchor := _best_anchor(row, column)) is not None
    ]
    columns = {anchor.column for anchor in anchors}
    required = {LineItemColumn.DESCRIPTION, LineItemColumn.LINE_TOTAL}
    optional_numeric = {LineItemColumn.QUANTITY, LineItemColumn.UNIT_PRICE}
    score = sum(_COLUMN_SCORES[anchor.column] for anchor in anchors)
    if not required.issubset(columns) or not columns.intersection(optional_numeric) or score < 5:
        return None

    description = next(anchor for anchor in anchors if anchor.column == LineItemColumn.DESCRIPTION)
    line_total = next(anchor for anchor in anchors if anchor.column == LineItemColumn.LINE_TOTAL)
    if description.center_x >= line_total.center_x:
        return None
    return DetectedTableHeader(
        page=row.page,
        row=row,
        columns=sorted(anchors, key=lambda anchor: anchor.center_x),
        score=score,
    )


def infer_column_ranges(header: DetectedTableHeader) -> list[ColumnRange]:
    anchors = sorted(header.columns, key=lambda anchor: anchor.center_x)
    boundaries = [
        (left.center_x + right.center_x) / 2
        for left, right in zip(anchors, anchors[1:], strict=False)
    ]
    starts = [0.0, *boundaries]
    ends = [*boundaries, 1.0]
    return [
        ColumnRange(column=anchor.column, x0=x0, x1=x1)
        for anchor, x0, x1 in zip(anchors, starts, ends, strict=True)
    ]


def column_for_word(word: WordToken, ranges: list[ColumnRange]) -> LineItemColumn | None:
    center = (word.bbox.x0 + word.bbox.x1) / 2
    for index, column_range in enumerate(ranges):
        if column_range.x0 <= center < column_range.x1:
            return column_range.column
        if index == len(ranges) - 1 and center == column_range.x1:
            return column_range.column
    return None
