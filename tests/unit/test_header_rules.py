from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from invoiceops.extraction.header_rules import (
    extract_currency,
    extract_invoice_date,
    extract_invoice_number,
    extract_subtotal,
    extract_tax,
    extract_total,
)
from invoiceops.extraction.layout import reconstruct_lines
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)

type Rule = Callable[[list[Any]], ExtractedField[Any]]


def document_from_lines(
    values: list[tuple[int, str, TextSource]],
) -> DocumentText:
    pages: list[PageText] = []
    for page_number in sorted({item[0] for item in values}):
        words: list[WordToken] = []
        page_lines = [item for item in values if item[0] == page_number]
        for line_number, (_, text, source) in enumerate(page_lines):
            for word_number, token in enumerate(text.split()):
                x0 = 0.05 + word_number * 0.08
                words.append(
                    WordToken(
                        text=token,
                        page=page_number,
                        bbox=BoundingBox(
                            x0=x0,
                            y0=0.05 + line_number * 0.08,
                            x1=min(x0 + 0.07, 1),
                            y1=0.1 + line_number * 0.08,
                        ),
                        block_number=0,
                        line_number=line_number,
                        word_number=word_number,
                        source=source,
                    )
                )
        source = page_lines[0][2]
        pages.append(
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
        )
    return DocumentText(
        pages=pages,
        used_ocr=any(page.source == TextSource.OCR for page in pages),
    )


def lines(*values: str, source: TextSource = TextSource.EMBEDDED) -> list[Any]:
    return reconstruct_lines(document_from_lines([(0, value, source) for value in values]))


@pytest.mark.parametrize(
    ("rule", "same_line", "next_label", "next_value", "expected"),
    [
        (extract_invoice_number, "Invoice No: INV-42", "Invoice Number", "INV-42", "INV-42"),
        (
            extract_invoice_date,
            "Invoice Date: 19/09/2026",
            "Date of Issue",
            "19 Sep 2026",
            date(2026, 9, 19),
        ),
        (extract_currency, "Currency: INR", "Currency", "INR", "INR"),
        (extract_subtotal, "Subtotal: 1,000.00", "Subtotal", "1,000.00", Decimal("1000.00")),
        (extract_tax, "GST: 180.00", "Tax Total", "180.00", Decimal("180.00")),
        (extract_total, "Grand Total: 1,180.00", "Amount Due", "1,180.00", Decimal("1180.00")),
    ],
)
def test_each_field_supports_same_and_next_line(
    rule: Rule,
    same_line: str,
    next_label: str,
    next_value: str,
    expected: object,
) -> None:
    same = rule(lines(same_line))
    following = rule(lines(next_label, next_value))

    assert same.status == ExtractionStatus.EXTRACTED
    assert same.value == expected
    assert same.evidence
    assert following.status == ExtractionStatus.EXTRACTED
    assert following.value == expected
    assert len(following.evidence) == 2
    assert following.rule_id is not None and ".next_line." in following.rule_id


@pytest.mark.parametrize(
    "rule",
    [
        extract_invoice_number,
        extract_invoice_date,
        extract_currency,
        extract_subtotal,
        extract_tax,
        extract_total,
    ],
)
def test_each_field_returns_missing_without_a_candidate(rule: Rule) -> None:
    result = rule(lines("Synthetic document without requested header"))

    assert result.status == ExtractionStatus.MISSING
    assert result.value is None
    assert result.evidence == []


@pytest.mark.parametrize(
    ("rule", "first", "second"),
    [
        (extract_invoice_number, "Invoice No: INV-1", "Invoice No: INV-2"),
        (extract_invoice_date, "Invoice Date: 19/09/2026", "Invoice Date: 20/09/2026"),
        (extract_currency, "Currency: INR", "Currency: EUR"),
        (extract_subtotal, "Subtotal: 100.00", "Subtotal: 200.00"),
        (extract_tax, "Tax Total: 18.00", "Tax Total: 36.00"),
        (extract_total, "Amount Due: 118.00", "Amount Due: 236.00"),
    ],
)
def test_equal_priority_conflicts_are_ambiguous(rule: Rule, first: str, second: str) -> None:
    result = rule(lines(first, second))

    assert result.status == ExtractionStatus.AMBIGUOUS
    assert result.value is None
    assert len(result.evidence) == 2
    assert result.rule_id is not None and result.rule_id.endswith(".ambiguous.v1")


@pytest.mark.parametrize(
    ("rule", "false_positive"),
    [
        (extract_invoice_number, "Invoice Number: 27ABCDE1234F1Z5"),
        (extract_invoice_date, "Due Date: 19/09/2026"),
        (extract_currency, "Total: $ 100.00"),
        (extract_currency, "Vendor: USD Corporation"),
        (extract_subtotal, "Discount subtotal: 50.00"),
        (extract_tax, "Tax rate: 18%"),
        (extract_total, "Tax Total: 180.00"),
    ],
)
def test_false_positive_labels_are_rejected(rule: Rule, false_positive: str) -> None:
    assert rule(lines(false_positive)).status == ExtractionStatus.MISSING


def test_total_priority_prevents_bare_total_from_overriding_amount_due() -> None:
    result = extract_total(lines("Total: 999.00", "Amount Due: 1180.00"))

    assert result.value == Decimal("1180.00")
    assert result.rule_id == "header.total.amount_due.same_line.v1"


@pytest.mark.parametrize(
    "excluded_label",
    [
        "Subtotal: 1000.00",
        "Tax Total: 180.00",
        "Total Tax: 180.00",
        "Quantity Total: 10",
        "Discount Total: 50.00",
    ],
)
def test_total_rejects_explicitly_excluded_aggregates(excluded_label: str) -> None:
    assert extract_total(lines(excluded_label)).status == ExtractionStatus.MISSING


def test_ocr_and_multi_page_evidence_is_preserved() -> None:
    document = document_from_lines(
        [
            (0, "Informational first page with enough text", TextSource.EMBEDDED),
            (1, "Invoice Number: OCR-42", TextSource.OCR),
        ]
    )

    result = extract_invoice_number(reconstruct_lines(document))

    assert result.value == "OCR-42"
    assert result.evidence[0].page == 1
    assert result.evidence[0].source == TextSource.OCR
