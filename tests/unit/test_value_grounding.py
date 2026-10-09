from datetime import date
from decimal import Decimal

import pytest

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.value_grounding import (
    ValueGroundedInvoiceExtractor,
    localize_header_value,
)
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus, TextSource
from tests.synthetic_documents import generated_invoice_pdf
from tests.unit.test_header_rules import document_from_lines


@pytest.mark.parametrize("source", [TextSource.EMBEDDED, TextSource.OCR])
@pytest.mark.parametrize(
    ("name", "label", "printed", "expected"),
    [
        ("invoice_number", "Invoice No:", "SYN-42", "SYN-42"),
        ("invoice_date", "Invoice Date:", "19 Sep 2026", date(2026, 9, 19)),
        ("subtotal", "Subtotal:", "1,000.00", Decimal("1000")),
        ("tax", "Tax Total:", "180.00", Decimal("180")),
        ("total", "Grand Total:", "1,180.00", Decimal("1180")),
    ],
)
@pytest.mark.parametrize("next_line", [False, True])
def test_value_evidence_excludes_label(
    name: str, label: str, printed: str, expected: object, source: TextSource, next_line: bool
) -> None:
    values = (
        [(0, label, source), (0, printed, source)]
        if next_line
        else [(0, f"{label} {printed}", source)]
    )
    document = document_from_lines(values)
    before = getattr(DeterministicInvoiceExtractor().extract(document), name)
    after = getattr(ValueGroundedInvoiceExtractor().extract(document), name)
    assert after.value == before.value == expected
    assert after.status == before.status == ExtractionStatus.EXTRACTED
    assert after.evidence[0].text == printed
    assert after.evidence[0].source == source
    assert (
        after.evidence[0].bbox.x0 > before.evidence[0].bbox.x0
        if not next_line
        else (after.evidence[0].bbox.y0 > before.evidence[0].bbox.y0)
    )


def test_conflicting_and_missing_headers_remain_unchanged() -> None:
    document = document_from_lines(
        [
            (0, "Invoice No: SYN-A", TextSource.EMBEDDED),
            (0, "Invoice No: SYN-B", TextSource.EMBEDDED),
        ]
    )
    before = DeterministicInvoiceExtractor().extract(document)
    after = ValueGroundedInvoiceExtractor().extract(document)
    assert after == before
    assert after.invoice_number.status == ExtractionStatus.AMBIGUOUS
    assert after.total.status == ExtractionStatus.MISSING


def test_repeated_equal_values_do_not_guess_one_location() -> None:
    document = document_from_lines(
        [
            (0, "Grand Total: 118.00", TextSource.OCR),
            (1, "Grand Total: 118.00", TextSource.OCR),
        ]
    )
    before = DeterministicInvoiceExtractor().extract(document)
    after = ValueGroundedInvoiceExtractor().extract(document)
    assert after.total == before.total


def test_unmatched_value_keeps_original_evidence() -> None:
    document = document_from_lines([(0, "Synthetic source", TextSource.EMBEDDED)])
    field = ExtractedField[object](
        value=Decimal("42"),
        status=ExtractionStatus.EXTRACTED,
        evidence=evidence_from_words(document.pages[0].words),
        rule_id="synthetic.v1",
    )
    assert localize_header_value(field, document) == field


def test_generated_pdf_preserves_values_and_line_items() -> None:
    from invoiceops.extraction.preprocessing import DocumentTextExtractor

    document = DocumentTextExtractor().extract(generated_invoice_pdf(), "application/pdf")
    before = DeterministicInvoiceExtractor().extract(document)
    after = ValueGroundedInvoiceExtractor().extract(document)
    assert before.line_items == after.line_items
    assert before.currency == after.currency
    for name in ("invoice_number", "invoice_date", "subtotal", "tax", "total"):
        original, candidate = getattr(before, name), getattr(after, name)
        assert candidate.value == original.value
        assert candidate.status == original.status
        assert candidate.rule_id == original.rule_id
        assert len(candidate.evidence) == 1


def test_duplicate_text_outside_original_evidence_is_not_considered() -> None:
    document = document_from_lines(
        [
            (0, "Grand Total: 118.00", TextSource.OCR),
            (0, "Reference: 118.00", TextSource.OCR),
        ]
    )
    before = DeterministicInvoiceExtractor().extract(document)
    after = ValueGroundedInvoiceExtractor().extract(document)
    assert after.total.value == before.total.value
    assert after.total.evidence[0].text == "118.00"
    assert after.total.evidence[0].bbox.y0 == document.pages[0].words[0].bbox.y0
