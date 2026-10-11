from decimal import Decimal
from typing import Any

import pytest

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.financial_summary_guard import (
    GUARD_NAME,
    GUARD_VERSION,
    FinancialSummaryGuardExtractor,
    guard_total,
)
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.version import CURRENT_EXTRACTION_STRATEGIES
from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)
from invoiceops.schemas.matching import MatchDecision, ReasonCode
from tests.matching.helpers import invoice, purchase_order


def make_document(rows: list[list[tuple[str, float]]], *, page: int = 0) -> DocumentText:
    words = []
    for index, row in enumerate(rows):
        for ordinal, (text, x) in enumerate(row):
            words.append(
                WordToken(
                    text=text,
                    page=page,
                    bbox=dict(x0=x, x1=x + 0.035, y0=0.1 + index * 0.04, y1=0.12 + index * 0.04),
                    block_number=index,
                    line_number=0,
                    word_number=ordinal,
                    source=TextSource.EMBEDDED,
                )
            )
    return DocumentText(
        used_ocr=False,
        pages=[
            PageText(
                page=page,
                width=600,
                height=800,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=words,
            )
        ],
    )


@pytest.mark.parametrize("label", ["Total", "Grand total", "Invoice total", "Amount due"])
def test_unambiguous_explicit_and_generic_totals(label: str) -> None:
    document = make_document([[(label, 0.1), ("100.00", 0.6)]])
    baseline = DeterministicInvoiceExtractor().extract(document)
    candidate = FinancialSummaryGuardExtractor().extract(document)
    assert candidate == baseline
    assert candidate.total.value == Decimal(100)


def competing_document(repeated: bool = False, *, page: int = 0) -> DocumentText:
    document = make_document(
        [
            [("Net", 0.4), ("Tax", 0.6), ("Gross", 0.8)],
            [
                ("Total", 0.1),
                ("100", 0.4),
                ("100" if repeated else "20", 0.6),
                ("100" if repeated else "120", 0.8),
            ],
        ],
        page=page,
    )
    # Separate PDF blocks let the baseline follow Total to the first amount.
    # Visual reconstruction still observes the competing columns on one row.
    for index, token in enumerate(document.pages[0].words[-4:]):
        token.block_number = 10 + index
    return document


@pytest.mark.parametrize("repeated", [False, True])
def test_multiple_columns_abstain_with_bounded_evidence(repeated: bool) -> None:
    document = competing_document(repeated)
    baseline = DeterministicInvoiceExtractor().extract(document)
    result = FinancialSummaryGuardExtractor().extract(document)
    assert baseline.total.status == ExtractionStatus.EXTRACTED
    assert result.total.status == ExtractionStatus.AMBIGUOUS
    assert result.total.value is None
    assert result.total.evidence
    assert {s.page for s in result.total.evidence} == {0}
    assert result.model_dump(exclude={"total"}) == baseline.model_dump(exclude={"total"})


def test_unique_direct_printed_gross_can_remain_usable() -> None:
    document = make_document(
        [
            [
                ("Total", 0.1),
                ("Net", 0.25),
                ("100", 0.30),
                ("Tax", 0.45),
                ("20", 0.50),
                ("Gross", 0.65),
                ("120", 0.70),
            ]
        ]
    )
    candidate = FinancialSummaryGuardExtractor().extract(document)
    assert candidate.total.status == ExtractionStatus.EXTRACTED
    assert candidate.total.value == Decimal(120)
    assert candidate.total.rule_id == "financial_summary.inline_gross_unique.v1"
    assert candidate.total.evidence[0].text == "120"


def test_wrapped_label_and_split_numeric_tokens() -> None:
    document = make_document([[("Total", 0.1)], [("100.00", 0.1)]])
    assert FinancialSummaryGuardExtractor().extract(document).total.value == Decimal(100)
    document = make_document([[("Total", 0.1), ("1,", 0.6), ("200.00", 0.64)]])
    assert FinancialSummaryGuardExtractor().extract(document).total.value == Decimal(1200)


def test_nearby_tax_prose_does_not_change_single_total() -> None:
    document = make_document([[("Tax", 0.1), ("20", 0.6)], [("Total", 0.1), ("100", 0.6)]])
    assert FinancialSummaryGuardExtractor().extract(document).total.value == Decimal(100)


def test_pages_do_not_share_column_role_labels() -> None:
    first = make_document([[("Net", 0.4), ("Tax", 0.6), ("Gross", 0.8)]])
    second = make_document([[("Total", 0.1), ("100", 0.4), ("20", 0.6)]], page=1)
    for index, token in enumerate(second.pages[0].words):
        token.block_number = index
    document = DocumentText(pages=first.pages + second.pages, used_ocr=False)
    assert (
        FinancialSummaryGuardExtractor().extract(document).total.status
        == ExtractionStatus.AMBIGUOUS
    )
    assert FinancialSummaryGuardExtractor().extract(document).total.rule_id == (
        "financial_summary.unresolved_multi_amount_total.v1"
    )
    third = competing_document(page=2)
    document = DocumentText(pages=first.pages + third.pages, used_ocr=False)
    assert (
        FinancialSummaryGuardExtractor().extract(document).total.status
        == ExtractionStatus.AMBIGUOUS
    )


def test_missing_and_ambiguous_totals_remain_unchanged() -> None:
    for rows in ([], [[("Grand total", 0.1), ("100", 0.6)], [("Grand total", 0.1), ("200", 0.6)]]):
        document = make_document(rows)
        baseline = DeterministicInvoiceExtractor().extract(document)
        assert FinancialSummaryGuardExtractor().extract(document).total == baseline.total


def test_missing_or_wrong_page_evidence_abstains() -> None:
    document = make_document([[("Total", 0.1), ("100", 0.6)]])
    unsupported = ExtractedField[Decimal].model_construct(
        value=Decimal(100),
        status=ExtractionStatus.EXTRACTED,
        evidence=[],
        rule_id="header.total.total.same_line.v1",
    )
    assert guard_total(unsupported, document).status == ExtractionStatus.AMBIGUOUS
    source = make_document([[("100", 0.6)]], page=1).pages[0].words
    unsupported.evidence = evidence_from_words(source)
    assert guard_total(unsupported, document).status == ExtractionStatus.AMBIGUOUS


@pytest.mark.parametrize("status", [ExtractionStatus.AMBIGUOUS, ExtractionStatus.MISSING])
def test_existing_matching_policy_requires_review(status: ExtractionStatus) -> None:
    complete = invoice()
    assert match_invoice(complete, purchase_order()).decision == MatchDecision.MATCHED
    complete.total = ExtractedField[Any](value=None, status=status, evidence=[])
    result = match_invoice(complete, purchase_order())
    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert ReasonCode.INVOICE_SCHEMA_INCOMPLETE in result.reason_codes


def test_candidate_is_not_in_production_selection() -> None:
    assert (GUARD_NAME, GUARD_VERSION) not in CURRENT_EXTRACTION_STRATEGIES
    assert ("deterministic-baseline", "0.2.0") in CURRENT_EXTRACTION_STRATEGIES
