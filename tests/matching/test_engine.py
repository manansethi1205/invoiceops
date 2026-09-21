from decimal import Decimal

import pytest

from invoiceops.matching.engine import match_invoice
from invoiceops.matching.normalization import normalize_description
from invoiceops.schemas.extraction import Invoice, InvoiceLine
from invoiceops.schemas.matching import MatchDecision, MatchingPolicy, MatchResult, ReasonCode
from tests.matching.helpers import (
    extracted,
    invoice,
    invoice_line,
    missing,
    purchase_order,
)


def reasons(result: MatchResult) -> set[ReasonCode]:
    return set(result.reason_codes)


def test_exact_match_and_reordered_invoice_lines() -> None:
    normal = match_invoice(invoice(), purchase_order())
    reordered = match_invoice(
        invoice(
            lines=[
                invoice_line("Mounting Bracket", "4", "50", "200"),
                invoice_line("Industrial Filter", "2", "500", "1000"),
            ]
        ),
        purchase_order(),
    )

    assert normal.decision == reordered.decision == MatchDecision.MATCHED
    assert [item.po_line_number for item in reordered.line_assignments] == ["2", "1"]


def test_currency_mismatch_requires_review() -> None:
    result = match_invoice(invoice(currency="USD"), purchase_order(currency="INR"))

    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert ReasonCode.CURRENCY_MISMATCH in reasons(result)


@pytest.mark.parametrize(
    ("invoice_price", "expected_decision"),
    [
        ("101.00", MatchDecision.MATCHED),
        ("101.0001", MatchDecision.NEEDS_REVIEW),
    ],
)
def test_unit_price_relative_tolerance_boundary(
    invoice_price: str, expected_decision: MatchDecision
) -> None:
    quantity = Decimal("0.001")
    price = Decimal(invoice_price)
    line_total = quantity * price
    result = match_invoice(
        invoice(
            subtotal=str(line_total),
            tax="0",
            total=str(line_total),
            lines=[invoice_line("Precision Part", "0.001", invoice_price, str(line_total))],
        ),
        purchase_order(lines=[("1", "Precision Part", "0.001", "100.00")]),
    )

    assert result.decision == expected_decision
    assert (ReasonCode.UNIT_PRICE_MISMATCH in reasons(result)) is (
        expected_decision == MatchDecision.NEEDS_REVIEW
    )


@pytest.mark.parametrize(
    ("line_total", "expected_decision"),
    [
        ("10.02", MatchDecision.MATCHED),
        ("10.0201", MatchDecision.NEEDS_REVIEW),
    ],
)
def test_absolute_amount_tolerance_boundary(
    line_total: str, expected_decision: MatchDecision
) -> None:
    result = match_invoice(
        invoice(
            subtotal=line_total,
            tax="0",
            total=line_total,
            lines=[invoice_line("Service", "1", "10", line_total)],
        ),
        purchase_order(lines=[("1", "Service", "1", "10")]),
    )

    assert result.decision == expected_decision


def test_quantity_mismatch_requires_review() -> None:
    result = match_invoice(
        invoice(
            subtotal="1700",
            tax="0",
            total="1700",
            lines=[
                invoice_line("Industrial Filter", "3", "500", "1500"),
                invoice_line("Mounting Bracket", "4", "50", "200"),
            ],
        ),
        purchase_order(),
    )
    assert ReasonCode.QUANTITY_MISMATCH in reasons(result)


@pytest.mark.parametrize(
    ("changed_invoice", "reason"),
    [
        (
            invoice(
                subtotal="1199",
                tax="216",
                total="1415",
                lines=[
                    invoice_line("Industrial Filter", "2", "500", "999"),
                    invoice_line("Mounting Bracket", "4", "50", "200"),
                ],
            ),
            ReasonCode.INVOICE_LINE_ARITHMETIC_MISMATCH,
        ),
        (invoice(subtotal="1199", tax="216", total="1415"), ReasonCode.INVOICE_SUBTOTAL_MISMATCH),
        (invoice(total="1417"), ReasonCode.INVOICE_TOTAL_MISMATCH),
    ],
)
def test_financial_arithmetic_failures_require_review(
    changed_invoice: Invoice, reason: ReasonCode
) -> None:
    result = match_invoice(changed_invoice, purchase_order())
    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert reason in reasons(result)


def test_extra_invoice_line_and_missing_po_line_are_explained() -> None:
    extra = match_invoice(
        invoice(
            subtotal="1210",
            tax="0",
            total="1210",
            lines=[
                invoice_line("Industrial Filter", "2", "500", "1000"),
                invoice_line("Mounting Bracket", "4", "50", "200"),
                invoice_line("Extra Washer", "10", "1", "10"),
            ],
        ),
        purchase_order(),
    )
    missing_po = match_invoice(
        invoice(
            subtotal="1000",
            tax="0",
            total="1000",
            lines=[invoice_line("Industrial Filter", "2", "500", "1000")],
        ),
        purchase_order(),
    )

    assert ReasonCode.EXTRA_INVOICE_LINE in reasons(extra)
    assert ReasonCode.PO_LINE_UNMATCHED in reasons(missing_po)


def test_low_similarity_and_ambiguous_candidates_never_match() -> None:
    low = match_invoice(
        invoice(
            subtotal="10",
            tax="0",
            total="10",
            lines=[invoice_line("Completely Different Service", "1", "10", "10")],
        ),
        purchase_order(lines=[("1", "Industrial Filter", "1", "10")]),
    )
    ambiguous = match_invoice(
        invoice(
            subtotal="10",
            tax="0",
            total="10",
            lines=[invoice_line("Blue Widget Premium", "1", "10", "10")],
        ),
        purchase_order(
            lines=[
                ("1", "Blue Widget Premium Pro", "1", "10"),
                ("2", "Blue Widget Premium Plus", "1", "10"),
            ]
        ),
    )

    assert ReasonCode.DESCRIPTION_BELOW_THRESHOLD in reasons(low)
    assert ReasonCode.DESCRIPTION_AMBIGUOUS in reasons(ambiguous)
    assert low.decision == ambiguous.decision == MatchDecision.NEEDS_REVIEW


def test_below_threshold_runner_up_does_not_create_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def score(_left: str, right: str) -> float:
        return {"Best Candidate": 0.86, "Below Threshold": 0.82}[right]

    monkeypatch.setattr("invoiceops.matching.engine.description_similarity", score)
    result = match_invoice(
        invoice(
            subtotal="10",
            tax="0",
            total="10",
            lines=[invoice_line("Fuzzy Input", "1", "10", "10")],
        ),
        purchase_order(
            lines=[
                ("1", "Best Candidate", "1", "10"),
                ("2", "Below Threshold", "1", "10"),
            ]
        ),
    )

    assert len(result.line_assignments) == 1
    assert ReasonCode.DESCRIPTION_AMBIGUOUS not in reasons(result)


def test_description_score_exactly_at_threshold_is_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "invoiceops.matching.engine.description_similarity",
        lambda _left, _right: 0.85,
    )
    result = match_invoice(
        invoice(
            subtotal="10",
            tax="0",
            total="10",
            lines=[invoice_line("Fuzzy Input", "1", "10", "10")],
        ),
        purchase_order(lines=[("1", "Candidate", "1", "10")]),
    )

    assert result.decision == MatchDecision.MATCHED
    assert result.line_assignments[0].description_score == 0.85


def test_missing_invoice_value_is_never_matched() -> None:
    incomplete_line = InvoiceLine(
        description=extracted("Industrial Filter"),
        quantity=extracted(Decimal("2")),
        unit_price=missing(),
        line_total=extracted(Decimal("1000")),
    )
    result = match_invoice(
        invoice(subtotal="1000", tax="0", total="1000", lines=[incomplete_line]),
        purchase_order(lines=[("1", "Industrial Filter", "2", "500")]),
    )

    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert ReasonCode.INVOICE_SCHEMA_INCOMPLETE in reasons(result)


def test_zero_po_price_does_not_divide_and_requires_exact_zero() -> None:
    result = match_invoice(
        invoice(
            subtotal="0.01",
            tax="0",
            total="0.01",
            lines=[invoice_line("Free Sample", "1", "0.01", "0.01")],
        ),
        purchase_order(lines=[("1", "Free Sample", "1", "0")]),
    )

    assert ReasonCode.UNIT_PRICE_MISMATCH in reasons(result)


def test_negative_invoice_amount_requires_review() -> None:
    result = match_invoice(
        invoice(
            subtotal="-10",
            tax="0",
            total="-10",
            lines=[invoice_line("Credit", "1", "-10", "-10")],
        ),
        purchase_order(lines=[("1", "Credit", "1", "0")]),
    )

    assert result.decision == MatchDecision.NEEDS_REVIEW
    assert ReasonCode.NEGATIVE_AMOUNT in reasons(result)


def test_every_review_has_reasons_and_human_readable_failed_checks() -> None:
    result = match_invoice(invoice(currency="USD"), purchase_order())
    failed = [
        check
        for check in result.checks
        + [check for assignment in result.line_assignments for check in assignment.checks]
        if check.status == "failed"
    ]
    assert result.reason_codes
    assert failed
    assert all(check.message for check in failed)


def test_normalization_preserves_alphanumeric_identifiers() -> None:
    assert normalize_description("  FILTER—AB-123 / Premium ") == "filter ab 123 premium"


def test_policy_decimal_tolerances_reject_float_inputs() -> None:
    with pytest.raises(ValueError, match="not floats"):
        MatchingPolicy(unit_price_relative_tolerance=0.01)
