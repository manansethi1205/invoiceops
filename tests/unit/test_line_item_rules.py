from decimal import Decimal

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.line_item_rules import extract_line_items
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


def cell_words(
    text: str,
    *,
    page: int,
    x0: float,
    y0: float,
    block: int,
    source: TextSource,
) -> list[WordToken]:
    words: list[WordToken] = []
    cursor = x0
    for word_number, value in enumerate(text.split()):
        width = max(0.025, len(value) * 0.009)
        words.append(
            WordToken(
                text=value,
                page=page,
                bbox=BoundingBox(x0=cursor, y0=y0, x1=min(cursor + width, 1), y1=y0 + 0.02),
                block_number=block,
                line_number=0,
                word_number=word_number,
                source=source,
            )
        )
        cursor += width + 0.008
    return words


def table_page(
    page: int,
    rows: list[tuple[float, str, str, str, str]],
    *,
    source: TextSource = TextSource.EMBEDDED,
    aliases: tuple[str, str, str, str] = ("Description", "Qty", "Unit Price", "Amount"),
) -> PageText:
    words: list[WordToken] = []
    positions = (0.08, 0.53, 0.67, 0.84)
    block = 0
    for x0, text in zip(positions, aliases, strict=True):
        words.extend(cell_words(text, page=page, x0=x0, y0=0.2, block=block, source=source))
        block += 1
    for y0, description, quantity, unit_price, line_total in rows:
        for x0, text in zip(
            positions,
            (description, quantity, unit_price, line_total),
            strict=True,
        ):
            if text:
                words.extend(
                    cell_words(text, page=page, x0=x0, y0=y0, block=block, source=source)
                )
            block += 1
    return PageText(
        page=page,
        width=600,
        height=800,
        source=source,
        ocr_reason=(
            OcrReason.NO_EMBEDDED_TEXT
            if source == TextSource.OCR
            else OcrReason.EMBEDDED_TEXT_SUFFICIENT
        ),
        words=words,
    )


def document(*pages: PageText) -> DocumentText:
    return DocumentText(
        pages=list(pages),
        used_ocr=any(page.source == TextSource.OCR for page in pages),
    )


def test_two_rows_extract_decimal_values_and_cell_evidence() -> None:
    page = table_page(
        0,
        [
            (0.25, "Industrial Filter", "2.5", "INR 500.00", "1,250.00"),
            (0.30, "Credit Bracket", "1", "(50.00)", "(50.00)"),
            (0.36, "Subtotal", "", "", "1,200.00"),
        ],
    )

    items = extract_line_items(document(page))

    assert len(items) == 2
    assert items[0].description.value == "Industrial Filter"
    assert items[0].quantity.value == Decimal("2.5")
    assert items[0].unit_price.value == Decimal("500.00")
    assert items[0].line_total.value == Decimal("1250.00")
    assert items[1].unit_price.value == Decimal("-50.00")
    assert items[1].line_total.value == Decimal("-50.00")
    for item in items:
        for field in (item.description, item.quantity, item.unit_price, item.line_total):
            assert field.evidence
            assert field.evidence[0].bbox.x0 <= field.evidence[0].bbox.x1


def test_missing_unit_price_stays_missing_and_is_not_inferred() -> None:
    page = table_page(
        0,
        [(0.25, "Service Fee", "2", "", "400.00")],
        aliases=("Particulars", "Units", "", "Net Amount"),
    )

    item = extract_line_items(document(page))[0]

    assert item.description.value == "Service Fee"
    assert item.quantity.value == Decimal("2")
    assert item.unit_price.status == ExtractionStatus.MISSING
    assert item.unit_price.value is None
    assert item.unit_price.evidence == []
    assert item.line_total.value == Decimal("400.00")


def test_description_continuations_attach_conservatively() -> None:
    page = table_page(
        0,
        [
            (0.23, "Industrial filtration", "", "", ""),
            (0.25, "unit with", "", "", ""),
            (0.28, "replacement assembly", "2", "500.00", "1,000.00"),
            (0.32, "Mounting Bracket", "4", "50.00", "200.00"),
            (0.34, "powder coated", "", "", ""),
            (0.40, "Grand Total", "", "", "1,200.00"),
        ],
    )

    items = extract_line_items(document(page))

    assert [item.description.value for item in items] == [
        "Industrial filtration unit with replacement assembly",
        "Mounting Bracket powder coated",
    ]
    assert all(
        item.description.rule_id == "line_item.description.continuation.v1" for item in items
    )


def test_repeated_headers_on_multiple_pages_preserve_order_and_ocr_source() -> None:
    first = table_page(0, [(0.25, "First Item", "1", "10.00", "10.00")])
    second = table_page(
        1,
        [(0.25, "Scanned Item", "3", "20.00", "60.00")],
        source=TextSource.OCR,
        aliases=("Item Description", "Quantity", "Rate", "Line Total"),
    )

    items = extract_line_items(document(first, second))

    assert [item.description.value for item in items] == ["First Item", "Scanned Item"]
    assert items[1].description.evidence[0].page == 1
    assert items[1].description.evidence[0].source == TextSource.OCR


def test_non_table_and_ignored_rows_do_not_become_items() -> None:
    no_header = PageText(
        page=0,
        width=600,
        height=800,
        source=TextSource.EMBEDDED,
        ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
        words=(
            cell_words(
                "Bank Details Account 12345",
                page=0,
                x0=0.08,
                y0=0.2,
                block=0,
                source=TextSource.EMBEDDED,
            )
            + cell_words(
                "Total quantity 10",
                page=0,
                x0=0.08,
                y0=0.3,
                block=1,
                source=TextSource.EMBEDDED,
            )
        ),
    )

    assert extract_line_items(document(no_header)) == []


def test_arithmetic_mismatch_is_preserved_without_inference() -> None:
    page = table_page(0, [(0.25, "Mismatch Item", "2", "100.00", "999.00")])

    item = extract_line_items(document(page))[0]

    assert item.quantity.value == Decimal("2")
    assert item.unit_price.value == Decimal("100.00")
    assert item.line_total.value == Decimal("999.00")


def test_description_quantity_and_price_is_valid_without_inventing_total() -> None:
    page = table_page(0, [(0.25, "Unextended Item", "3", "25.00", "")])

    item = extract_line_items(document(page))[0]

    assert item.description.value == "Unextended Item"
    assert item.quantity.value == Decimal("3")
    assert item.unit_price.value == Decimal("25.00")
    assert item.line_total.status == ExtractionStatus.MISSING
    assert item.line_total.value is None
    assert item.line_total.evidence == []


def test_mixed_source_cell_evidence_is_split_without_losing_words() -> None:
    words = cell_words(
        "Mixed source",
        page=0,
        x0=0.08,
        y0=0.25,
        block=1,
        source=TextSource.EMBEDDED,
    )
    words[1] = words[1].model_copy(update={"source": TextSource.OCR})

    evidence = evidence_from_words(words)

    assert len(evidence) == 2
    assert {span.source for span in evidence} == {TextSource.EMBEDDED, TextSource.OCR}
    assert {span.text for span in evidence} == {"Mixed", "source"}


def test_page_terms_bank_and_signature_rows_inside_table_are_ignored() -> None:
    page = table_page(
        0,
        [
            (0.24, "Page 1 of 2", "", "", ""),
            (0.27, "Bank Details", "", "", "99999"),
            (0.30, "Terms and Conditions", "", "", "100.00"),
            (0.33, "Authorized Signatory", "", "", "200.00"),
            (0.36, "Actual Item", "1", "20.00", "20.00"),
        ],
    )

    items = extract_line_items(document(page))

    assert [item.description.value for item in items] == ["Actual Item"]


def test_currency_marker_in_quantity_is_not_accepted_as_quantity() -> None:
    page = table_page(0, [(0.25, "Malformed Item", "INR 2", "", "")])

    assert extract_line_items(document(page)) == []


def test_footer_prefix_inside_a_real_description_does_not_stop_the_table() -> None:
    page = table_page(
        0,
        [
            (0.25, "Tax Consulting Service", "1", "300.00", "300.00"),
            (0.30, "GST 18%", "", "", "54.00"),
            (0.35, "Another Item", "1", "20.00", "20.00"),
        ],
    )

    items = extract_line_items(document(page))

    assert [item.description.value for item in items] == ["Tax Consulting Service"]
