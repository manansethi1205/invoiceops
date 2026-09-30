from decimal import Decimal

from invoiceops.extraction.supporting import extract_goods_receipt, extract_purchase_order
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


def document_from_rows(rows: list[list[tuple[str, float]]]) -> DocumentText:
    words: list[WordToken] = []
    for line_number, row in enumerate(rows):
        for word_number, (value, x0) in enumerate(row):
            words.append(
                WordToken(
                    text=value,
                    page=0,
                    bbox=BoundingBox(
                        x0=x0,
                        y0=0.05 + line_number * 0.06,
                        x1=min(1, x0 + max(0.04, len(value) * 0.008)),
                        y1=0.08 + line_number * 0.06,
                    ),
                    block_number=0,
                    line_number=line_number,
                    word_number=word_number,
                    source=TextSource.EMBEDDED,
                )
            )
    return DocumentText(
        pages=[
            PageText(
                page=0,
                width=1000,
                height=1000,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=words,
            )
        ],
        used_ocr=False,
    )


def test_extracts_purchase_order_with_evidence() -> None:
    document = document_from_rows(
        [
            [("Purchase", 0.05), ("Order", 0.13), ("No:", 0.22), ("PO-100", 0.3)],
            [("Order", 0.05), ("Date:", 0.13), ("30/09/2026", 0.25)],
            [("Vendor:", 0.05), ("Synthetic", 0.2), ("Supplier", 0.32)],
            [("Currency:", 0.05), ("INR", 0.2)],
            [
                ("Line", 0.01),
                ("Description", 0.05),
                ("Qty", 0.5),
                ("Unit", 0.62),
                ("Price", 0.68),
                ("Amount", 0.84),
            ],
            [("1", 0.01), ("Widgets", 0.05), ("2", 0.52), ("10.00", 0.67), ("20.00", 0.86)],
            [("Sub", 0.05), ("Total", 0.12), ("20.00", 0.86)],
            [("Tax", 0.05), ("2.00", 0.86)],
            [("Grand", 0.05), ("Total", 0.13), ("22.00", 0.86)],
        ]
    )

    result = extract_purchase_order(document)

    assert result.po_number.value == "PO-100"
    assert result.currency.value == "INR"
    assert result.total.value == Decimal("22.00")
    assert result.po_number.evidence
    assert len(result.line_items) == 1
    assert result.line_items[0].line_number.value == "1"
    assert result.line_items[0].line_number.evidence
    assert result.line_items[0].ordered_quantity.value == Decimal("2")


def test_conflicting_purchase_order_numbers_abstain_as_ambiguous() -> None:
    document = document_from_rows(
        [
            [("Purchase", 0.05), ("Order", 0.13), ("No:", 0.22), ("PO-100", 0.3)],
            [("PO", 0.05), ("Number:", 0.13), ("PO-200", 0.3)],
        ]
    )

    result = extract_purchase_order(document)

    assert result.po_number.value is None
    assert result.po_number.status.value == "ambiguous"
    assert len(result.po_number.evidence) == 2


def test_extracts_receipt_rows_without_inventing_rejected_quantity() -> None:
    document = document_from_rows(
        [
            [("Goods", 0.05), ("Receipt", 0.13), ("No:", 0.23), ("GR-9", 0.31)],
            [("PO", 0.05), ("No:", 0.11), ("PO-100", 0.2)],
            [("Received", 0.05), ("Date:", 0.16), ("30/09/2026", 0.28)],
            [("Supplier:", 0.05), ("Synthetic", 0.2), ("Supplier", 0.32)],
            [("Description", 0.05), ("Received", 0.5), ("Accepted", 0.68), ("Rejected", 0.85)],
            [("Widgets", 0.05), ("2", 0.53), ("2", 0.71)],
        ]
    )

    result = extract_goods_receipt(document)

    assert result.receipt_number.value == "GR-9"
    assert result.referenced_po_number.value == "PO-100"
    assert len(result.line_items) == 1
    assert result.line_items[0].accepted_quantity.value == Decimal("2")
    assert result.line_items[0].rejected_quantity.value is None
    assert result.line_items[0].rejected_quantity.evidence == []
