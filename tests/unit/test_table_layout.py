from invoiceops.extraction.table_layout import (
    LineItemColumn,
    detect_table_header,
    infer_column_ranges,
    reconstruct_visual_rows,
)
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


def token(
    text: str,
    *,
    page: int,
    x0: float,
    y0: float,
    block: int,
    height: float = 0.02,
    source: TextSource = TextSource.EMBEDDED,
) -> WordToken:
    return WordToken(
        text=text,
        page=page,
        bbox=BoundingBox(x0=x0, y0=y0, x1=min(x0 + 0.06, 1), y1=y0 + height),
        block_number=block,
        line_number=0,
        word_number=0,
        source=source,
    )


def document(*pages: tuple[TextSource, list[WordToken]]) -> DocumentText:
    return DocumentText(
        pages=[
            PageText(
                page=page_number,
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
            for page_number, (source, words) in enumerate(pages)
        ],
        used_ocr=any(source == TextSource.OCR for source, _ in pages),
    )


def test_visual_rows_group_separate_blocks_and_order_left_to_right() -> None:
    words = [
        token("Amount", page=0, x0=0.82, y0=0.2, block=4),
        token("Description", page=0, x0=0.08, y0=0.2, block=1),
        token("Qty", page=0, x0=0.52, y0=0.2, block=2),
        token("Rate", page=0, x0=0.67, y0=0.2, block=3),
        token("next", page=0, x0=0.08, y0=0.25, block=5),
    ]

    rows = reconstruct_visual_rows(document((TextSource.EMBEDDED, words)))

    assert len(rows) == 2
    assert [word.text for word in rows[0].words] == ["Description", "Qty", "Rate", "Amount"]
    assert [word.text for word in rows[1].words] == ["next"]


def test_visual_rows_handle_font_sizes_pages_and_ocr_provenance() -> None:
    page_zero = [
        token("Description", page=0, x0=0.08, y0=0.2, block=1, height=0.03),
        token("Qty", page=0, x0=0.52, y0=0.21, block=2, height=0.015),
    ]
    page_one = [
        token(
            "Scanned",
            page=1,
            x0=0.08,
            y0=0.2,
            block=1,
            source=TextSource.OCR,
        )
    ]

    rows = reconstruct_visual_rows(
        document((TextSource.EMBEDDED, page_zero), (TextSource.OCR, page_one))
    )

    assert len(rows) == 2
    assert len(rows[0].words) == 2
    assert [row.page for row in rows] == [0, 1]
    assert rows[1].words[0].source == TextSource.OCR


def test_header_detection_supports_aliases_multiword_names_and_ranges() -> None:
    words = [
        token("Item", page=0, x0=0.08, y0=0.2, block=1),
        token("Description", page=0, x0=0.15, y0=0.2, block=1),
        token("QUANTITY", page=0, x0=0.52, y0=0.2, block=2),
        token("Unit", page=0, x0=0.65, y0=0.2, block=3),
        token("Price", page=0, x0=0.72, y0=0.2, block=3),
        token("Line", page=0, x0=0.84, y0=0.2, block=4),
        token("Total", page=0, x0=0.91, y0=0.2, block=4),
    ]
    row = reconstruct_visual_rows(document((TextSource.EMBEDDED, words)))[0]

    header = detect_table_header(row)

    assert header is not None
    assert header.score == 6
    assert [anchor.column for anchor in header.columns] == list(LineItemColumn)
    assert header.columns[0].matched_text == "Item Description"
    ranges = infer_column_ranges(header)
    assert ranges[0].x0 == 0
    assert ranges[-1].x1 == 1
    assert all(
        left.x1 == right.x0 for left, right in zip(ranges, ranges[1:], strict=False)
    )


def test_header_requires_description_total_and_numeric_column() -> None:
    ordinary = [
        token("Item", page=0, x0=0.08, y0=0.2, block=1),
        token("Amount", page=0, x0=0.82, y0=0.2, block=2),
    ]
    tax_summary = [
        token("Tax", page=0, x0=0.08, y0=0.3, block=3),
        token("Rate", page=0, x0=0.52, y0=0.3, block=4),
        token("Amount", page=0, x0=0.82, y0=0.3, block=5),
    ]
    rows = reconstruct_visual_rows(document((TextSource.EMBEDDED, ordinary + tax_summary)))

    assert detect_table_header(rows[0]) is None
    assert detect_table_header(rows[1]) is None
