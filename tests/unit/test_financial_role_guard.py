from decimal import Decimal

import pytest

from invoiceops.extraction.financial_role_guard import (
    ROLE_GUARD_VERSION,
    FinancialRoleGuardExtractor,
)
from invoiceops.extraction.financial_summary_guard import FinancialSummaryGuardExtractor
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.version import CURRENT_EXTRACTION_STRATEGIES
from invoiceops.schemas.extraction import DocumentText, ExtractionStatus, TextSource
from tests.evaluation.financial_role_fixtures import challenge_fixture


def source(chunks: list[tuple[float, float, str]]) -> DocumentText:
    body, _ = challenge_fixture([(x, y, t, None) for x, y, t in chunks])
    return DocumentTextExtractor().extract(body, "application/pdf")


@pytest.mark.parametrize("balance", ["80.00", "120.00"])
@pytest.mark.parametrize("label", ["Gross amount", "Grand total", "Invoice total"])
def test_independent_gross_proof_overrides_balance_without_arithmetic(
    balance: str, label: str
) -> None:
    document = source(
        [
            (50, 200, "Amount due"),
            (200, 200, balance),
            (50, 230, "Prepayment"),
            (200, 230, "40.00"),
            (50, 260, label),
            (200, 260, "120.00"),
        ]
    )
    baseline = DeterministicInvoiceExtractor().extract(document)
    result = FinancialRoleGuardExtractor().extract(document)
    assert baseline.total.value == Decimal(balance)
    assert result.total.value == Decimal("120")
    assert result.total.rule_id == "financial_role.explicit_gross_unique.v1"
    assert result.total.evidence[0].bbox.y0 > baseline.total.evidence[0].bbox.y0
    assert result.model_dump(exclude={"total"}) == baseline.model_dump(exclude={"total"})


@pytest.mark.parametrize("label", ["Amount due", "Total payable", "Net payable"])
def test_balance_alone_or_credits_cannot_prove_gross(label: str) -> None:
    for extras in ([], [(50, 260, "Credits"), (200, 260, "20.00")]):
        document = source([(50, 200, label), (200, 200, "80.00"), *extras])
        result = FinancialRoleGuardExtractor().extract(document)
        assert result.total.status == ExtractionStatus.AMBIGUOUS
        assert result.total.value is None and result.total.evidence


@pytest.mark.parametrize("duplicate", ["120.00", "140.00"])
def test_multiple_gross_occurrences_remain_ambiguous(duplicate: str) -> None:
    document = source(
        [
            (50, 200, "Amount due"),
            (200, 200, "80.00"),
            (50, 260, "Gross amount"),
            (200, 260, "120.00"),
            (50, 300, "Gross amount"),
            (200, 300, duplicate),
        ]
    )
    assert (
        FinancialRoleGuardExtractor().extract(document).total.status == ExtractionStatus.AMBIGUOUS
    )


def test_separate_reference_panel_recovers_correct_total() -> None:
    document = source(
        [(50, 200, "Total"), (200, 200, "100.00"), (400, 200, "Reference"), (510, 200, "7")]
    )
    assert (
        FinancialSummaryGuardExtractor().extract(document).total.status
        == ExtractionStatus.AMBIGUOUS
    )
    result = FinancialRoleGuardExtractor().extract(document)
    assert result.total.value == Decimal(100)
    assert result.total.rule_id == "financial_role.separated_reference.v1"
    assert all("Reference" not in e.text and "7" not in e.text for e in result.total.evidence)


@pytest.mark.parametrize("problem", ["narrow", "merged", "skewed", "currency", "tax_panel"])
def test_uncertain_reference_geometry_or_semantics_abstains(problem: str) -> None:
    chunks = [
        (50, 200, "Total"),
        (200, 200, "100.00"),
        (260 if problem == "narrow" else 400, 200, "Reference"),
        (380 if problem == "narrow" else 510, 200, "USD 7" if problem == "currency" else "7"),
    ]
    if problem == "tax_panel":
        chunks += [(400, 180, "Tax")]
    document = source(chunks)
    if problem == "merged":
        for w in document.pages[0].words:
            w.block_number = 0
            w.line_number = 0
    if problem == "skewed":
        for w in document.pages[0].words:
            if w.text == "Reference":
                w.bbox = w.bbox.model_copy(
                    update={"y0": w.bbox.y0 + 0.007, "y1": w.bbox.y1 + 0.007}
                )
    assert FinancialRoleGuardExtractor().extract(document).total.status in {
        ExtractionStatus.AMBIGUOUS,
        ExtractionStatus.MISSING,
    }


def test_ocr_provenance_and_missing_totals_remain_conservative() -> None:
    document = source([(50, 200, "Amount due"), (200, 200, "80.00")])
    for page in document.pages:
        page.source = TextSource.OCR
        for word in page.words:
            word.source = TextSource.OCR
    result = FinancialRoleGuardExtractor().extract(document)
    assert result.total.status == ExtractionStatus.AMBIGUOUS
    assert all(e.source == TextSource.OCR for e in result.total.evidence)
    empty = source([(50, 200, "No financial summary")])
    assert FinancialRoleGuardExtractor().extract(empty).total == (
        DeterministicInvoiceExtractor().extract(empty).total
    )
    assert ROLE_GUARD_VERSION == "0.4.0"
    assert ("deterministic-financial-summary-guard", "0.4.0") not in CURRENT_EXTRACTION_STRATEGIES


@pytest.mark.parametrize("problem", ["multiple", "unbound", "wrong_page", "distant", "degenerate"])
def test_unresolved_or_remote_gross_cannot_repair_payable(problem: str) -> None:
    document = source(
        [
            (50, 200, "Amount due"),
            (200, 200, "80.00"),
            (50, 260, "Gross amount"),
            (200, 260, "120.00"),
        ]
    )
    if problem == "multiple":
        document = source(
            [
                (50, 200, "Amount due"),
                (200, 200, "80.00"),
                (50, 260, "Gross amount"),
                (200, 260, "120.00"),
                (350, 260, "20.00"),
            ]
        )
    elif problem in {"unbound", "degenerate"}:
        for w in document.pages[0].words:
            if w.text == "120.00":
                center = (w.bbox.y0 + w.bbox.y1) / 2
                w.bbox = w.bbox.model_copy(
                    update=(
                        {"y0": center, "y1": center}
                        if problem == "degenerate"
                        else {"y0": w.bbox.y0 + 0.01, "y1": w.bbox.y1 + 0.01}
                    )
                )
    elif problem == "wrong_page":
        page = document.pages[0]
        other = page.model_copy(deep=True, update={"page": 1})
        other.words = [w for w in other.words if w.bbox.y0 > 0.3]
        for w in other.words:
            w.page = 1
        page.words = [w for w in page.words if w.bbox.y0 < 0.3]
        document.pages.append(other)
    else:
        document = source(
            [
                (50, 200, "Amount due"),
                (200, 200, "80.00"),
                (50, 700, "Gross amount"),
                (200, 700, "120.00"),
            ]
        )
    assert (
        FinancialRoleGuardExtractor().extract(document).total.status == ExtractionStatus.AMBIGUOUS
    )


def test_repeated_financial_amounts_and_existing_matching_gate() -> None:
    from invoiceops.matching.engine import match_invoice
    from invoiceops.schemas.matching import MatchDecision
    from tests.matching.helpers import invoice, purchase_order

    document = source(
        [(50, 200, "Total"), (200, 200, "100.00"), (50, 260, "Total"), (200, 260, "100.00")]
    )
    result = FinancialRoleGuardExtractor().extract(document)
    assert result.total.status == ExtractionStatus.AMBIGUOUS
    complete = invoice()
    assert match_invoice(complete, purchase_order()).decision == MatchDecision.MATCHED
    complete.total = result.total
    assert match_invoice(complete, purchase_order()).decision == MatchDecision.NEEDS_REVIEW
