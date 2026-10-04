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
SUPPORTING_EXTRACTOR_VERSION = "0.2.0"
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


def extract_purchase_order(document: DocumentText) -> ExtractedPurchaseOrder:
    lines = reconstruct_lines(document)
    po_lines = _purchase_order_rows(document)
    return _purchase_order_from_lines(lines, po_lines)


def _purchase_order_from_lines(
    lines: list[TextLine], po_lines: list[ExtractedPurchaseOrderLine]
) -> ExtractedPurchaseOrder:
    return ExtractedPurchaseOrder(
        po_number=_labeled_text(
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
    lines = reconstruct_lines(document)
    return ExtractedGoodsReceipt(
        receipt_number=_labeled_text(
            lines,
            re.compile(
                r"\b(?:goods\s*receipt|receipt|delivery\s*note)\s*(?:number|no\.?|#)?\b", re.I
            ),
            rule="goods_receipt.number",
        ),
        referenced_po_number=_labeled_text(
            lines,
            re.compile(r"\b(?:purchase\s*order|po)\s*(?:number|no\.?|#)?\b", re.I),
            rule="goods_receipt.purchase_order_number",
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
