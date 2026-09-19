from collections.abc import Sequence

import pymupdf
import pytest

from invoiceops.extraction.errors import EncryptedDocumentError, UnreadableDocumentError
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import OcrReason, TextSource


def pdf_bytes(*page_texts: str) -> bytes:
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page(width=400, height=300)
            if text:
                page.insert_textbox(pymupdf.Rect(30, 30, 370, 270), text, fontsize=11)
        return document.tobytes()
    finally:
        document.close()


def encrypted_pdf_bytes() -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Synthetic encrypted invoice")
        return document.tobytes(
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="synthetic-owner",
            user_pw="synthetic-user",
        )
    finally:
        document.close()


def fail_if_ocr_runs(_page: pymupdf.Page) -> Sequence[object]:
    raise AssertionError("OCR must not run for sufficient embedded text")


def test_digital_pdf_uses_embedded_words_and_preserves_page_numbers() -> None:
    body = pdf_bytes(
        "Synthetic invoice number INV-2026-0042 vendor Example Components currency INR total 1180",
        "Second page contains delivery notes and eight meaningful words for deterministic testing",
    )
    result = DocumentTextExtractor(ocr_word_extractor=fail_if_ocr_runs).extract(
        body, "application/pdf"
    )

    assert result.used_ocr is False
    assert [page.page for page in result.pages] == [0, 1]
    assert all(page.source == TextSource.EMBEDDED for page in result.pages)
    assert all(page.ocr_reason == OcrReason.EMBEDDED_TEXT_SUFFICIENT for page in result.pages)
    assert result.pages[0].words[0].page == 0
    assert result.pages[1].words[0].page == 1


def test_all_word_coordinates_are_normalized() -> None:
    result = DocumentTextExtractor(ocr_word_extractor=fail_if_ocr_runs).extract(
        pdf_bytes(
            "Synthetic invoice number INV-100 vendor Example Limited currency INR "
            "subtotal 1000 total 1180"
        ),
        "application/pdf",
    )

    assert result.pages[0].words
    for word in result.pages[0].words:
        assert 0 <= word.bbox.x0 <= word.bbox.x1 <= 1
        assert 0 <= word.bbox.y0 <= word.bbox.y1 <= 1


def test_blank_page_attempts_ocr_once_and_returns_no_words() -> None:
    calls = 0

    def empty_ocr(_page: pymupdf.Page) -> Sequence[object]:
        nonlocal calls
        calls += 1
        return []

    result = DocumentTextExtractor(ocr_word_extractor=empty_ocr).extract(
        pdf_bytes(""), "application/pdf"
    )

    assert calls == 1
    assert result.used_ocr is True
    assert result.pages[0].source == TextSource.OCR
    assert result.pages[0].ocr_reason == OcrReason.NO_EMBEDDED_TEXT
    assert result.pages[0].words == []


def test_ocr_words_keep_source_and_normalized_provenance() -> None:
    calls = 0

    def synthetic_ocr(_page: pymupdf.Page) -> Sequence[object]:
        nonlocal calls
        calls += 1
        return [(40.0, 30.0, 160.0, 60.0, "Scanned", 2, 3, 4)]

    result = DocumentTextExtractor(ocr_word_extractor=synthetic_ocr).extract(
        pdf_bytes(""), "application/pdf"
    )

    assert calls == 1
    word = result.pages[0].words[0]
    assert word.source == TextSource.OCR
    assert word.page == 0
    assert (word.block_number, word.line_number, word.word_number) == (2, 3, 4)
    assert word.bbox.model_dump() == {"x0": 0.1, "y0": 0.1, "x1": 0.4, "y1": 0.2}


def test_malformed_ocr_word_data_is_not_silently_dropped() -> None:
    def malformed_ocr(_page: pymupdf.Page) -> Sequence[object]:
        return [(1.0, 2.0, "incomplete")]

    with pytest.raises(UnreadableDocumentError, match="malformed word data"):
        DocumentTextExtractor(ocr_word_extractor=malformed_ocr).extract(
            pdf_bytes(""), "application/pdf"
        )


@pytest.mark.parametrize(
    ("text", "expected_reason"),
    [
        (
            "six extraordinarily descriptive embedded invoice words",
            OcrReason.TOO_FEW_EMBEDDED_WORDS,
        ),
        ("a b c d e f g h", OcrReason.EMBEDDED_TEXT_TOO_SHORT),
    ],
)
def test_either_insufficient_text_threshold_triggers_ocr_once(
    text: str, expected_reason: OcrReason
) -> None:
    calls = 0

    def empty_ocr(_page: pymupdf.Page) -> Sequence[object]:
        nonlocal calls
        calls += 1
        return []

    result = DocumentTextExtractor(ocr_word_extractor=empty_ocr).extract(
        pdf_bytes(text), "application/pdf"
    )

    assert calls == 1
    assert result.pages[0].ocr_reason == expected_reason


def test_corrupt_document_raises_clear_error() -> None:
    with pytest.raises(UnreadableDocumentError, match="could not be decoded"):
        DocumentTextExtractor().extract(b"%PDF-1.7 not actually a PDF", "application/pdf")


def test_encrypted_document_raises_clear_error() -> None:
    with pytest.raises(EncryptedDocumentError, match="password-protected"):
        DocumentTextExtractor().extract(encrypted_pdf_bytes(), "application/pdf")
