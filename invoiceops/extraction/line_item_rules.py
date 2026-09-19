import re
from decimal import Decimal

from pydantic import BaseModel, Field

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.normalization import normalize_whitespace, parse_money
from invoiceops.extraction.table_layout import (
    ColumnRange,
    LineItemColumn,
    VisualRow,
    column_for_word,
    detect_table_header,
    infer_column_ranges,
    reconstruct_visual_rows,
)
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    InvoiceLine,
    WordToken,
)


class ParsedTableRow(BaseModel):
    page: int = Field(ge=0)
    y0: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    description_words: list[WordToken]
    quantity_words: list[WordToken]
    unit_price_words: list[WordToken]
    line_total_words: list[WordToken]
    description_continued: bool = False


_FOOTER_PATTERN = re.compile(
    r"^\s*(sub\s*total|tax|gst|cgst|sgst|igst|discount|shipping|round off|"
    r"amount due|grand total|invoice total|net payable)\b",
    re.IGNORECASE,
)
_IGNORED_ROW_PATTERN = re.compile(
    r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|terms(?:\s+and\s+conditions)?|"
    r"bank(?:\s+details)?|signature|authorized signatory)\b",
    re.IGNORECASE,
)
_CURRENCY_MARKER = re.compile(
    r"(?:[₹€£$]|\b(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD|RS\.?)\b)",
    re.IGNORECASE,
)


def _words_text(words: list[WordToken]) -> str:
    return normalize_whitespace(" ".join(word.text for word in words))


def parse_quantity(words: list[WordToken]) -> Decimal | None:
    text = _words_text(words)
    if not text or _CURRENCY_MARKER.search(text):
        return None
    return parse_money(text)


def parse_money_cell(words: list[WordToken]) -> Decimal | None:
    return parse_money(_words_text(words)) if words else None


def parse_table_row(row: VisualRow, ranges: list[ColumnRange]) -> ParsedTableRow:
    assigned: dict[LineItemColumn, list[WordToken]] = {
        column: [] for column in LineItemColumn
    }
    for word in row.words:
        column = column_for_word(word, ranges)
        if column is not None:
            assigned[column].append(word)
    if assigned[LineItemColumn.DESCRIPTION] and all(
        not any(character.isdigit() for character in word.text)
        and _CURRENCY_MARKER.search(word.text) is None
        for word in row.words
    ):
        assigned[LineItemColumn.DESCRIPTION] = list(row.words)
        assigned[LineItemColumn.QUANTITY] = []
        assigned[LineItemColumn.UNIT_PRICE] = []
        assigned[LineItemColumn.LINE_TOTAL] = []
    return ParsedTableRow(
        page=row.page,
        y0=row.y0,
        y1=row.y1,
        description_words=assigned[LineItemColumn.DESCRIPTION],
        quantity_words=assigned[LineItemColumn.QUANTITY],
        unit_price_words=assigned[LineItemColumn.UNIT_PRICE],
        line_total_words=assigned[LineItemColumn.LINE_TOTAL],
    )


def is_probable_line_item(row: ParsedTableRow) -> bool:
    has_description = bool(_words_text(row.description_words))
    has_quantity = parse_quantity(row.quantity_words) is not None
    has_unit_price = parse_money_cell(row.unit_price_words) is not None
    has_total = parse_money_cell(row.line_total_words) is not None
    return has_description and (has_total or (has_quantity and has_unit_price))


def _description_only(row: ParsedTableRow) -> bool:
    return bool(row.description_words) and not (
        row.quantity_words or row.unit_price_words or row.line_total_words
    )


def _missing_decimal() -> ExtractedField[Decimal]:
    return ExtractedField[Decimal](
        value=None,
        status=ExtractionStatus.MISSING,
        evidence=[],
        rule_id=None,
    )


def _decimal_field(
    words: list[WordToken],
    value: Decimal | None,
    rule_id: str,
) -> ExtractedField[Decimal]:
    if value is None:
        return _missing_decimal()
    return ExtractedField[Decimal](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=evidence_from_words(words),
        rule_id=rule_id,
    )


def _to_invoice_line(row: ParsedTableRow) -> InvoiceLine:
    description = _words_text(row.description_words)
    return InvoiceLine(
        description=ExtractedField[str](
            value=description,
            status=ExtractionStatus.EXTRACTED,
            evidence=evidence_from_words(row.description_words),
            rule_id=(
                "line_item.description.continuation.v1"
                if row.description_continued
                else "line_item.description.column.v1"
            ),
        ),
        quantity=_decimal_field(
            row.quantity_words,
            parse_quantity(row.quantity_words),
            "line_item.quantity.column.v1",
        ),
        unit_price=_decimal_field(
            row.unit_price_words,
            parse_money_cell(row.unit_price_words),
            "line_item.unit_price.column.v1",
        ),
        line_total=_decimal_field(
            row.line_total_words,
            parse_money_cell(row.line_total_words),
            "line_item.line_total.column.v1",
        ),
    )


def _row_text(row: VisualRow) -> str:
    return _words_text(row.words)


def _is_footer(row: VisualRow) -> bool:
    text = _row_text(row)
    match = _FOOTER_PATTERN.search(text)
    if match is None:
        return False
    label = normalize_whitespace(match.group(1)).lower()
    if label in {
        "subtotal",
        "sub total",
        "amount due",
        "grand total",
        "invoice total",
        "net payable",
    }:
        return True
    remainder = text[match.end() :]
    remainder_without_currency = re.sub(
        r"\b(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD|RS\.?)\b",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    return re.search(r"[A-Za-z]", remainder_without_currency) is None


def _is_ignored(row: VisualRow) -> bool:
    return _IGNORED_ROW_PATTERN.search(_row_text(row)) is not None


def _resolve_continuations(rows: list[ParsedTableRow]) -> list[InvoiceLine]:
    valid_indices = [index for index, row in enumerate(rows) if is_probable_line_item(row)]
    prefixes: dict[int, list[WordToken]] = {}
    suffixes: dict[int, list[WordToken]] = {}
    for index, continuation in enumerate(rows):
        if not _description_only(continuation):
            continue
        previous = max((item for item in valid_indices if item < index), default=None)
        following = min((item for item in valid_indices if item > index), default=None)
        if previous is None and following is None:
            continue
        if previous is None:
            target_index = following
            prepend = True
        elif following is None:
            target_index = previous
            prepend = False
        else:
            previous_gap = continuation.y0 - rows[previous].y1
            following_gap = rows[following].y0 - continuation.y1
            prepend = following_gap < previous_gap
            target_index = following if prepend else previous
        if target_index is None:
            continue
        collection = prefixes if prepend else suffixes
        collection.setdefault(target_index, []).extend(continuation.description_words)
    for index in valid_indices:
        if index not in prefixes and index not in suffixes:
            continue
        target = rows[index]
        target.description_words = (
            prefixes.get(index, [])
            + target.description_words
            + suffixes.get(index, [])
        )
        target.description_continued = True
    return [_to_invoice_line(rows[index]) for index in valid_indices]


def extract_line_items(document: DocumentText) -> list[InvoiceLine]:
    visual_rows = reconstruct_visual_rows(document)
    items: list[InvoiceLine] = []
    for page in sorted({row.page for row in visual_rows}):
        page_rows = [row for row in visual_rows if row.page == page]
        section: list[ParsedTableRow] = []
        ranges: list[ColumnRange] | None = None
        for row in page_rows:
            header = detect_table_header(row)
            if header is not None:
                if ranges is not None:
                    items.extend(_resolve_continuations(section))
                ranges = infer_column_ranges(header)
                section = []
                continue
            if ranges is None:
                continue
            if _is_footer(row):
                items.extend(_resolve_continuations(section))
                ranges = None
                section = []
                continue
            if _is_ignored(row):
                continue
            section.append(parse_table_row(row, ranges))
        if ranges is not None:
            items.extend(_resolve_continuations(section))
    return items
