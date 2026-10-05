import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from invoiceops.extraction.candidates import FieldCandidate, resolve_candidates
from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.header_rules import (
    extract_currency,
    extract_subtotal,
    extract_tax,
    extract_total,
)
from invoiceops.extraction.layout import TextLine, reconstruct_lines
from invoiceops.extraction.line_item_rules import extract_line_items
from invoiceops.extraction.normalization import (
    normalize_identifier,
    normalize_whitespace,
    parse_invoice_date,
    parse_money,
)
from invoiceops.extraction.table_layout import VisualRow, reconstruct_visual_rows
from invoiceops.schemas.cases import (
    ExtractedGoodsReceipt,
    ExtractedGoodsReceiptLine,
    ExtractedPurchaseOrder,
    ExtractedPurchaseOrderLine,
)
from invoiceops.schemas.extraction import DocumentText, ExtractedField, ExtractionStatus, WordToken

SUPPORTING_EXTRACTOR_NAME = "deterministic-supporting-documents"
SUPPORTING_EXTRACTOR_VERSION = "0.3.0"
SUPPORTING_SCHEMA_VERSION = "1.0"
_OTHER_LABEL = re.compile(
    r"^\s*(?:order date|po date|issue date|vendor|supplier|seller|buyer|customer|"
    r"bill to|currency|subtotal|sub total|tax|total|receipt date|received date|"
    r"delivery date)\b",
    re.IGNORECASE,
)


def _missing[T]() -> ExtractedField[T]:
    return ExtractedField[T](value=None, status=ExtractionStatus.MISSING, evidence=[])


def _labeled_text(
    lines: list[TextLine],
    pattern: re.Pattern[str],
    *,
    rule: str,
    normalize: Callable[[str], str] = normalize_whitespace,
) -> ExtractedField[str]:
    candidates: list[FieldCandidate[str]] = []
    for index, line in enumerate(lines):
        match = pattern.search(line.text)
        if match is None:
            continue
        raw = normalize_whitespace(line.text[match.end() :].lstrip(" :#.-"))
        evidence_words = line.words
        if not raw and index + 1 < len(lines) and lines[index + 1].page == line.page:
            following = normalize_whitespace(lines[index + 1].text)
            if _OTHER_LABEL.search(following) is None:
                raw = following
                evidence_words = [*line.words, *lines[index + 1].words]
        value = normalize(raw)
        if value:
            candidates.append(
                FieldCandidate(
                    value=value,
                    evidence=evidence_from_words(evidence_words),
                    rule_id=f"{rule}.labeled.v1",
                    priority=100,
                )
            )
    return resolve_candidates(
        candidates,
        comparison_key=normalize_identifier,
        ambiguous_rule_id=f"{rule}.ambiguous.v1",
    )


def _labeled_date(
    lines: list[TextLine], pattern: re.Pattern[str], *, rule: str
) -> ExtractedField[date]:
    candidates: list[FieldCandidate[date]] = []
    for index, line in enumerate(lines):
        match = pattern.search(line.text)
        if match is None:
            continue
        raw = normalize_whitespace(line.text[match.end() :].lstrip(" :#.-"))
        evidence_words = line.words
        value = parse_invoice_date(raw)
        if value is None and index + 1 < len(lines) and lines[index + 1].page == line.page:
            value = parse_invoice_date(lines[index + 1].text)
            evidence_words = [*line.words, *lines[index + 1].words]
        if value is not None:
            candidates.append(
                FieldCandidate(
                    value=value,
                    evidence=evidence_from_words(evidence_words),
                    rule_id=f"{rule}.labeled.v1",
                    priority=100,
                )
            )
    return resolve_candidates(
        candidates,
        comparison_key=lambda item: item,
        ambiguous_rule_id=f"{rule}.ambiguous.v1",
    )


_PO_LABEL = re.compile(
    r"(?:purchase\s+order(?:\s+(?:no\.?|number|#))?|"
    r"p\.?o\.?(?:\s+(?:no\.?|number|#)|:))\s*:?",
    re.I,
)
_RECEIPT_LABEL = re.compile(
    r"(?:goods\s+receipt|receipt|delivery\s+note)"
    r"(?:\s+(?:no\.?|number|#)|:)?\s*:?",
    re.I,
)
_OTHER_HEADER = re.compile(
    r"^(?:order\s+date|po\s+date|issue\s+date|received\s+date|"
    r"delivery\s+date|receipt\s+date|vendor|supplier|seller|buyer|"
    r"customer|bill\s+to|currency|subtotal|sub\s+total|tax|"
    r"grand\s+total|total|description|item|line)\b",
    re.I,
)
_IDENTIFIER_VALUE = re.compile(r"[A-Z0-9][A-Z0-9./_-]*", re.I)


def _identifier_label_length(words: list[WordToken], pattern: re.Pattern[str]) -> int:
    # Match only a complete label prefix. A bare PO token and PO-106 are not labels.
    for size in range(min(4, len(words)), 0, -1):
        candidate = normalize_whitespace(" ".join(word.text for word in words[:size]))
        if pattern.fullmatch(candidate):
            return size
    return 0


def _identifier_value(words: list[WordToken]) -> tuple[str, list[WordToken]] | None:
    if not words or _OTHER_HEADER.match(" ".join(word.text for word in words)):
        return None
    chosen: list[WordToken] = []
    for word in words[:3]:
        if not re.fullmatch(r"[A-Za-z0-9./_-]+", word.text):
            break
        if chosen and word.bbox.x0 - chosen[-1].bbox.x1 > 0.08:
            break
        chosen.append(word)
    if not chosen:
        return None
    raw = normalize_whitespace(" ".join(word.text for word in chosen))
    raw = re.sub(r"\s*([/-])\s*", r"\1", raw)
    if not _IDENTIFIER_VALUE.fullmatch(raw) or not normalize_identifier(raw):
        return None
    return raw, chosen


def _layout_identifier(
    document: DocumentText, *, pattern: re.Pattern[str], rule: str
) -> ExtractedField[str]:
    rows = reconstruct_visual_rows(document)
    candidates: list[FieldCandidate[str]] = []
    for index, row in enumerate(rows):
        length = _identifier_label_length(row.words, pattern)
        if not length:
            continue
        label = row.words[:length]
        value_words = row.words[length:]
        if value_words:
            # The value must follow the label on the same row, not overlap it.
            value_words = [word for word in value_words if word.bbox.x0 >= label[-1].bbox.x0]
            if value_words and value_words[0].bbox.x0 - label[-1].bbox.x1 > 0.45:
                value_words = []
        if not value_words and index + 1 < len(rows):
            below = rows[index + 1]
            gap = below.y0 - row.y1
            if (
                below.page == row.page
                and 0 <= gap <= 0.045
                and below.words[0].bbox.x0 >= label[0].bbox.x0 - 0.025
                and below.words[0].bbox.x0 - label[-1].bbox.x1 <= 0.45
                and not _identifier_label_length(below.words, pattern)
            ):
                value_words = below.words
        parsed = _identifier_value(value_words)
        if parsed is None:
            continue
        value, evidence_words = parsed
        candidates.append(
            FieldCandidate(
                value=value,
                evidence=evidence_from_words(evidence_words),
                rule_id=f"{rule}.layout.v2",
                priority=100,
            )
        )
    return resolve_candidates(
        candidates, comparison_key=normalize_identifier, ambiguous_rule_id=f"{rule}.ambiguous.v2"
    )


def extract_purchase_order(document: DocumentText) -> ExtractedPurchaseOrder:
    lines = reconstruct_lines(document)
    po_lines = _purchase_order_rows(document)
    return _purchase_order_from_lines(
        lines,
        po_lines,
        po_number=_layout_identifier(document, pattern=_PO_LABEL, rule="purchase_order.number"),
    )


def _purchase_order_from_lines(
    lines: list[TextLine],
    po_lines: list[ExtractedPurchaseOrderLine],
    *,
    po_number: ExtractedField[str] | None = None,
) -> ExtractedPurchaseOrder:
    return ExtractedPurchaseOrder(
        po_number=po_number
        if po_number is not None
        else _labeled_text(
            lines,
            re.compile(r"\b(?:purchase\s*order|po)\s*(?:number|no\.?|#)?\b", re.I),
            rule="purchase_order.number",
        ),
        issue_date=_labeled_date(
            lines,
            re.compile(r"\b(?:po\s*date|order\s*date|issue\s*date|date\s*of\s*issue)\b", re.I),
            rule="purchase_order.issue_date",
        ),
        vendor=_labeled_text(
            lines,
            re.compile(r"\b(?:vendor|supplier|seller)\b", re.I),
            rule="purchase_order.vendor",
        ),
        buyer=_labeled_text(
            lines,
            re.compile(r"\b(?:buyer|bill\s*to|customer)\b", re.I),
            rule="purchase_order.buyer",
        ),
        currency=extract_currency(lines),
        subtotal=extract_subtotal(lines),
        tax=extract_tax(lines),
        total=extract_total(lines),
        line_items=po_lines,
    )


_PO_LINE_HEADERS: dict[str, set[str]] = {
    "line_number": {"line", "line no", "line number", "item no", "sr no", "s no", "#"},
    "description": {"description", "item", "product", "details"},
    "quantity": {"quantity", "qty", "ordered", "ordered qty"},
    "unit_price": {"unit price", "rate", "price"},
    "line_total": {"amount", "line total", "total"},
}
_PO_TABLE_FOOTER = re.compile(
    r"^\s*(?:sub\s*total|subtotal|tax|discount|amount\s+due|grand\s+total|total)\b",
    re.I,
)


def _po_header_anchors(row: VisualRow) -> dict[str, float] | None:
    anchors: dict[str, float] = {}
    for index, _word in enumerate(row.words):
        for size in (2, 1):
            segment = row.words[index : index + size]
            text = normalize_whitespace(" ".join(item.text for item in segment)).lower()
            normalized = text.replace(".", "")
            for name, aliases in _PO_LINE_HEADERS.items():
                if name not in anchors and normalized in aliases:
                    anchors[name] = sum(
                        (item.bbox.x0 + item.bbox.x1) / 2 for item in segment
                    ) / len(segment)
    required = {"description", "line_total"}
    if not required.issubset(anchors) or not {"quantity", "unit_price"}.intersection(anchors):
        return None
    return anchors


def _purchase_order_rows(document: DocumentText) -> list[ExtractedPurchaseOrderLine]:
    result: list[ExtractedPurchaseOrderLine] = []
    boundaries: list[tuple[str, float, float]] = []
    previous_page = -1
    previous_y1 = 0.0
    for row in reconstruct_visual_rows(document):
        anchors = _po_header_anchors(row)
        if anchors is not None:
            ordered = sorted(anchors.items(), key=lambda item: item[1])
            cuts = [
                (left[1] + right[1]) / 2 for left, right in zip(ordered, ordered[1:], strict=False)
            ]
            boundaries = [
                (item[0], [0.0, *cuts][index], [*cuts, 1.0][index])
                for index, item in enumerate(ordered)
            ]
            continue
        if not boundaries:
            continue
        if _PO_TABLE_FOOTER.search(_row_text(row)):
            boundaries = []
            continue
        cells: dict[str, list[WordToken]] = {name: [] for name in _PO_LINE_HEADERS}
        for word in row.words:
            center = (word.bbox.x0 + word.bbox.x1) / 2
            for name, x0, x1 in boundaries:
                if x0 <= center <= x1:
                    cells[name].append(word)
                    break
        description = normalize_whitespace(" ".join(word.text for word in cells["description"]))
        numbers = {
            name: parse_money(" ".join(word.text for word in cells[name])) if cells[name] else None
            for name in ("quantity", "unit_price", "line_total")
        }
        if description and not cells["line_number"] and not any(cells[name] for name in numbers):
            # Only a close, description-only row may continue the preceding row.
            if result and row.page == previous_page and 0 <= row.y0 - previous_y1 <= 0.045:
                old = result[-1].description
                if old.value is not None:
                    result[-1] = result[-1].model_copy(
                        update={
                            "description": ExtractedField[str](
                                value=f"{old.value} {description}",
                                status=ExtractionStatus.EXTRACTED,
                                evidence=[
                                    *old.evidence,
                                    *evidence_from_words(cells["description"]),
                                ],
                                rule_id="purchase_order.line.description.wrapped.v2",
                            )
                        }
                    )
                    previous_y1 = row.y1
            continue
        # A populated but undecodable numeric cell makes row association uncertain.
        if not description or not any(value is not None for value in numbers.values()):
            continue
        if any(cells[name] and numbers[name] is None for name in numbers):
            continue
        raw_number = normalize_whitespace(" ".join(word.text for word in cells["line_number"]))
        normalized = normalize_identifier(raw_number) if raw_number else ""

        def text_field(
            name: str, value: str, *, row_cells: dict[str, list[WordToken]] = cells
        ) -> ExtractedField[str]:
            if not value:
                return _missing()
            return ExtractedField[str](
                value=value,
                status=ExtractionStatus.EXTRACTED,
                evidence=evidence_from_words(row_cells[name]),
                rule_id=f"purchase_order.line.{name}.column.v2",
            )

        def money_field(
            name: str,
            *,
            row_cells: dict[str, list[WordToken]] = cells,
            row_numbers: dict[str, Decimal | None] = numbers,
        ) -> ExtractedField[Decimal]:
            value = row_numbers[name]
            if value is None:
                return _missing()
            return ExtractedField[Decimal](
                value=value,
                status=ExtractionStatus.EXTRACTED,
                evidence=evidence_from_words(row_cells[name]),
                rule_id=f"purchase_order.line.{name}.column.v2",
            )

        result.append(
            ExtractedPurchaseOrderLine(
                line_number=text_field("line_number", normalized),
                description=text_field("description", description),
                ordered_quantity=money_field("quantity"),
                unit_price=money_field("unit_price"),
                line_total=money_field("line_total"),
            )
        )
        previous_page, previous_y1 = row.page, row.y1
    seen: dict[str, int] = {}
    for index, line in enumerate(result):
        if line.line_number.value is None:
            continue
        number = line.line_number.value
        if number in seen:
            for duplicate_index in (seen[number], index):
                current = result[duplicate_index].line_number
                result[duplicate_index] = result[duplicate_index].model_copy(
                    update={
                        "line_number": ExtractedField[str](
                            value=None,
                            status=ExtractionStatus.AMBIGUOUS,
                            evidence=current.evidence,
                            rule_id="purchase_order.line.number.duplicate.v2",
                        )
                    }
                )
        else:
            seen[number] = index
    return result


def extract_purchase_order_v1(document: DocumentText) -> ExtractedPurchaseOrder:
    """Historical 0.1.0 behavior for reproducible before/after evaluation only."""
    lines = reconstruct_lines(document)
    invoice_style_lines = extract_line_items(document)
    line_numbers = _legacy_purchase_order_line_numbers(document)
    aligned = (
        line_numbers
        if len(line_numbers) == len(invoice_style_lines)
        else [_missing() for _ in invoice_style_lines]
    )
    return _purchase_order_from_lines(
        lines,
        [
            ExtractedPurchaseOrderLine(
                line_number=number,
                description=item.description,
                ordered_quantity=item.quantity,
                unit_price=item.unit_price,
                line_total=item.line_total,
            )
            for item, number in zip(invoice_style_lines, aligned, strict=True)
        ],
    )


def _legacy_purchase_order_line_numbers(document: DocumentText) -> list[ExtractedField[str]]:
    result: list[ExtractedField[str]] = []
    boundaries: list[tuple[str, float, float]] = []
    for row in reconstruct_visual_rows(document):
        anchors = _po_header_anchors(row)
        if anchors is not None and "line_number" in anchors:
            ordered = sorted(anchors.items(), key=lambda item: item[1])
            cuts = [
                (left[1] + right[1]) / 2 for left, right in zip(ordered, ordered[1:], strict=False)
            ]
            boundaries = [
                (item[0], [0.0, *cuts][index], [*cuts, 1.0][index])
                for index, item in enumerate(ordered)
            ]
            continue
        if not boundaries:
            continue
        if _PO_TABLE_FOOTER.search(_row_text(row)):
            boundaries = []
            continue
        cells: dict[str, list[WordToken]] = {name: [] for name in _PO_LINE_HEADERS}
        for word in row.words:
            center = (word.bbox.x0 + word.bbox.x1) / 2
            for name, x0, x1 in boundaries:
                if x0 <= center <= x1:
                    cells[name].append(word)
                    break
        raw_number = normalize_whitespace(" ".join(word.text for word in cells["line_number"]))
        description = normalize_whitespace(" ".join(word.text for word in cells["description"]))
        numeric_cells = [
            parse_money(" ".join(word.text for word in cells[name]))
            for name in ("quantity", "unit_price", "line_total")
            if cells[name]
        ]
        if (
            not raw_number
            or not description
            or not any(value is not None for value in numeric_cells)
        ):
            continue
        normalized = normalize_identifier(raw_number)
        if normalized:
            result.append(
                ExtractedField[str](
                    value=normalized,
                    status=ExtractionStatus.EXTRACTED,
                    evidence=evidence_from_words(cells["line_number"]),
                    rule_id="purchase_order.line.number.column.v1",
                )
            )
    return result


_RECEIPT_HEADERS: dict[str, set[str]] = {
    "description": {"description", "item", "product", "details"},
    "received_quantity": {"received", "received qty", "delivered", "delivered qty"},
    "accepted_quantity": {"accepted", "accepted qty", "quantity", "qty"},
    "rejected_quantity": {"rejected", "rejected qty", "damaged"},
}
_RECEIPT_FOOTER = re.compile(r"^\s*(?:total|remarks|received by|signature)\b", re.I)


def _row_text(row: VisualRow) -> str:
    return normalize_whitespace(" ".join(word.text for word in row.words))


def _header_anchors(row: VisualRow) -> dict[str, float] | None:
    anchors: dict[str, float] = {}
    for index, _word in enumerate(row.words):
        for size in (2, 1):
            segment = row.words[index : index + size]
            text = normalize_whitespace(" ".join(item.text for item in segment)).lower()
            for name, aliases in _RECEIPT_HEADERS.items():
                if name not in anchors and text in aliases:
                    anchors[name] = sum(
                        (item.bbox.x0 + item.bbox.x1) / 2 for item in segment
                    ) / len(segment)
    if "description" not in anchors or not {
        "received_quantity",
        "accepted_quantity",
    }.intersection(anchors):
        return None
    return anchors


def _receipt_rows(document: DocumentText) -> list[ExtractedGoodsReceiptLine]:
    result: list[ExtractedGoodsReceiptLine] = []
    anchors: dict[str, float] | None = None
    boundaries: list[tuple[str, float, float]] = []
    for row in reconstruct_visual_rows(document):
        detected = _header_anchors(row)
        if detected is not None:
            anchors = detected
            ordered = sorted(anchors.items(), key=lambda item: item[1])
            cuts = [
                (left[1] + right[1]) / 2 for left, right in zip(ordered, ordered[1:], strict=False)
            ]
            boundaries = [
                (item[0], ([0.0, *cuts][index]), ([*cuts, 1.0][index]))
                for index, item in enumerate(ordered)
            ]
            continue
        if anchors is None:
            continue
        if _RECEIPT_FOOTER.search(_row_text(row)):
            anchors = None
            boundaries = []
            continue
        cells: dict[str, list[WordToken]] = {name: [] for name in _RECEIPT_HEADERS}
        for word in row.words:
            center = (word.bbox.x0 + word.bbox.x1) / 2
            for name, x0, x1 in boundaries:
                if x0 <= center <= x1:
                    cells[name].append(word)
                    break
        description = normalize_whitespace(" ".join(item.text for item in cells["description"]))
        quantities = {
            name: parse_money(" ".join(item.text for item in words)) if words else None
            for name, words in cells.items()
            if name != "description"
        }
        if not description or not any(value is not None for value in quantities.values()):
            continue

        def decimal_field(
            name: str,
            *,
            row_quantities: dict[str, Decimal | None] = quantities,
            row_cells: dict[str, list[WordToken]] = cells,
        ) -> ExtractedField[Decimal]:
            value = row_quantities.get(name)
            words = row_cells[name]
            if value is None:
                return _missing()
            return ExtractedField[Decimal](
                value=value,
                status=ExtractionStatus.EXTRACTED,
                evidence=evidence_from_words(words),
                rule_id=f"goods_receipt.line.{name}.column.v1",
            )

        result.append(
            ExtractedGoodsReceiptLine(
                description=ExtractedField[str](
                    value=description,
                    status=ExtractionStatus.EXTRACTED,
                    evidence=evidence_from_words(cells["description"]),
                    rule_id="goods_receipt.line.description.column.v1",
                ),
                received_quantity=decimal_field("received_quantity"),
                accepted_quantity=decimal_field("accepted_quantity"),
                rejected_quantity=decimal_field("rejected_quantity"),
            )
        )
    return result


def extract_goods_receipt(document: DocumentText) -> ExtractedGoodsReceipt:
    return _extract_goods_receipt(document, legacy_identifiers=False)


def extract_goods_receipt_v1(document: DocumentText) -> ExtractedGoodsReceipt:
    """Historical identifier behavior for before/after evaluation only."""
    return _extract_goods_receipt(document, legacy_identifiers=True)


def _extract_goods_receipt(
    document: DocumentText, *, legacy_identifiers: bool
) -> ExtractedGoodsReceipt:
    lines = reconstruct_lines(document)
    return ExtractedGoodsReceipt(
        receipt_number=_labeled_text(
            lines,
            re.compile(
                r"\b(?:goods\s*receipt|receipt|delivery\s*note)\s*(?:number|no\.?|#)?\b", re.I
            ),
            rule="goods_receipt.number",
        )
        if legacy_identifiers
        else _layout_identifier(document, pattern=_RECEIPT_LABEL, rule="goods_receipt.number"),
        referenced_po_number=_labeled_text(
            lines,
            re.compile(r"\b(?:purchase\s*order|po)\s*(?:number|no\.?|#)?\b", re.I),
            rule="goods_receipt.purchase_order_number",
        )
        if legacy_identifiers
        else _layout_identifier(
            document, pattern=_PO_LABEL, rule="goods_receipt.purchase_order_number"
        ),
        received_date=_labeled_date(
            lines,
            re.compile(r"\b(?:received\s*date|delivery\s*date|receipt\s*date)\b", re.I),
            rule="goods_receipt.received_date",
        ),
        supplier=_labeled_text(
            lines,
            re.compile(r"\b(?:supplier|vendor|delivered\s*by)\b", re.I),
            rule="goods_receipt.supplier",
        ),
        line_items=_receipt_rows(document),
    )
