from invoiceops.extraction.layout import reconstruct_lines
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


def word(
    text: str,
    *,
    page: int,
    block: int,
    line: int,
    number: int,
    x0: float,
    source: TextSource = TextSource.EMBEDDED,
) -> WordToken:
    return WordToken(
        text=text,
        page=page,
        bbox=BoundingBox(x0=x0, y0=0.1 + line * 0.1, x1=x0 + 0.08, y1=0.15 + line * 0.1),
        block_number=block,
        line_number=line,
        word_number=number,
        source=source,
    )


def test_reconstruct_lines_groups_orders_and_unions_words() -> None:
    words = [
        word("second", page=0, block=0, line=0, number=1, x0=0.3),
        word("first", page=0, block=0, line=0, number=0, x0=0.1),
        word("later", page=0, block=1, line=1, number=0, x0=0.2),
    ]
    document = DocumentText(
        pages=[
            PageText(
                page=0,
                width=100,
                height=100,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=words,
            )
        ],
        used_ocr=False,
    )

    lines = reconstruct_lines(document)

    assert [line.text for line in lines] == ["first second", "later"]
    assert lines[0].bbox.x0 == 0.1
    assert lines[0].bbox.x1 == 0.38
    assert [item.word_number for item in lines[0].words] == [0, 1]


def test_pages_never_merge_and_word_provenance_is_retained() -> None:
    embedded = word("same", page=0, block=0, line=0, number=0, x0=0.1)
    ocr = word(
        "coordinates",
        page=1,
        block=0,
        line=0,
        number=0,
        x0=0.1,
        source=TextSource.OCR,
    )
    document = DocumentText(
        pages=[
            PageText(
                page=0,
                width=100,
                height=100,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=[embedded],
            ),
            PageText(
                page=1,
                width=100,
                height=100,
                source=TextSource.OCR,
                ocr_reason=OcrReason.NO_EMBEDDED_TEXT,
                words=[ocr],
            ),
        ],
        used_ocr=True,
    )

    lines = reconstruct_lines(document)

    assert len(lines) == 2
    assert [line.page for line in lines] == [0, 1]
    assert lines[0].words[0].source == TextSource.EMBEDDED
    assert lines[1].words[0].source == TextSource.OCR
