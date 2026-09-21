from decimal import Decimal
from typing import Any

from invoiceops.schemas.extraction import EvidenceSpan, ExtractedField, ExtractionStatus, Invoice
from invoiceops.schemas.matching import (
    CheckSeverity,
    CheckStatus,
    MatchingPolicy,
    ReasonCode,
    ValidationCheck,
)


def decimal_string(value: Decimal) -> str:
    return format(value, "f")


def _evidence(*fields: ExtractedField[Any]) -> list[EvidenceSpan]:
    return [span for field in fields for span in field.evidence]


def _numeric_value(field: ExtractedField[Decimal]) -> Decimal | None:
    if field.status != ExtractionStatus.EXTRACTED:
        return None
    return field.value


def _check(
    *,
    code: ReasonCode,
    passed: bool,
    expected: Decimal | str | None,
    actual: Decimal | str | None,
    tolerance: Decimal | None,
    message: str,
    invoice_line_index: int | None = None,
    evidence: list[EvidenceSpan] | None = None,
) -> ValidationCheck:
    def serialize(value: Decimal | str | None) -> str | None:
        return decimal_string(value) if isinstance(value, Decimal) else value

    return ValidationCheck(
        code=code,
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        severity=CheckSeverity.INFO if passed else CheckSeverity.ERROR,
        expected=serialize(expected),
        actual=serialize(actual),
        tolerance=decimal_string(tolerance) if tolerance is not None else None,
        message=message,
        invoice_line_index=invoice_line_index,
        evidence=evidence or [],
    )


def validate_invoice_financials(
    invoice: Invoice, policy: MatchingPolicy
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    currency_present = (
        invoice.currency.status == ExtractionStatus.EXTRACTED
        and invoice.currency.value is not None
    )
    checks.append(
        _check(
            code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
            passed=currency_present,
            expected="currency present",
            actual=invoice.currency.value,
            tolerance=None,
            message=(
                "Invoice currency is present."
                if currency_present
                else "Invoice currency is missing or ambiguous."
            ),
            evidence=list(invoice.currency.evidence),
        )
    )
    total = _numeric_value(invoice.total)
    checks.append(
        _check(
            code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
            passed=total is not None,
            expected="total present",
            actual=total,
            tolerance=None,
            message=(
                "Invoice total is present."
                if total is not None
                else "Invoice total is missing or ambiguous."
            ),
            evidence=list(invoice.total.evidence),
        )
    )

    usable_line_totals: list[Decimal] = []
    for index, line in enumerate(invoice.line_items):
        quantity = _numeric_value(line.quantity)
        unit_price = _numeric_value(line.unit_price)
        line_total = _numeric_value(line.line_total)
        usable = quantity is not None and unit_price is not None and line_total is not None
        checks.append(
            _check(
                code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
                passed=usable,
                expected="quantity, unit price and line total present",
                actual="complete" if usable else "missing or ambiguous numeric value",
                tolerance=None,
                message=(
                    "Invoice line contains all required numeric values."
                    if usable
                    else "Invoice line is missing a required numeric value."
                ),
                invoice_line_index=index,
                evidence=_evidence(line.quantity, line.unit_price, line.line_total),
            )
        )
        for label, value, field in (
            ("quantity", quantity, line.quantity),
            ("unit price", unit_price, line.unit_price),
            ("line total", line_total, line.line_total),
        ):
            if value is not None and value < 0:
                checks.append(
                    _check(
                        code=ReasonCode.NEGATIVE_AMOUNT,
                        passed=False,
                        expected=f"non-negative {label}",
                        actual=value,
                        tolerance=None,
                        message=f"Invoice line {label} is negative and requires review.",
                        invoice_line_index=index,
                        evidence=list(field.evidence),
                    )
                )
        if usable:
            assert quantity is not None and unit_price is not None and line_total is not None
            expected_line_total = quantity * unit_price
            difference = abs(expected_line_total - line_total)
            checks.append(
                _check(
                    code=ReasonCode.INVOICE_LINE_ARITHMETIC_MISMATCH,
                    passed=difference <= policy.amount_absolute_tolerance,
                    expected=expected_line_total,
                    actual=line_total,
                    tolerance=policy.amount_absolute_tolerance,
                    message=(
                        "Invoice line arithmetic is within tolerance."
                        if difference <= policy.amount_absolute_tolerance
                        else "Invoice quantity multiplied by unit price differs from line total."
                    ),
                    invoice_line_index=index,
                    evidence=_evidence(line.quantity, line.unit_price, line.line_total),
                )
            )
            usable_line_totals.append(line_total)

    checks.append(
        _check(
            code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
            passed=bool(usable_line_totals),
            expected="at least one usable line",
            actual=str(len(usable_line_totals)),
            tolerance=None,
            message=(
                "Invoice contains at least one usable line."
                if usable_line_totals
                else "Invoice does not contain a usable line item."
            ),
        )
    )

    subtotal = _numeric_value(invoice.subtotal)
    if subtotal is None:
        checks.append(
            _check(
                code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
                passed=False,
                expected="subtotal present",
                actual=None,
                tolerance=None,
                message="Invoice subtotal is missing or ambiguous.",
                evidence=list(invoice.subtotal.evidence),
            )
        )
    elif usable_line_totals:
        expected_subtotal = sum(usable_line_totals, start=Decimal("0"))
        difference = abs(expected_subtotal - subtotal)
        checks.append(
            _check(
                code=ReasonCode.INVOICE_SUBTOTAL_MISMATCH,
                passed=difference <= policy.amount_absolute_tolerance,
                expected=expected_subtotal,
                actual=subtotal,
                tolerance=policy.amount_absolute_tolerance,
                message=(
                    "Invoice subtotal is within tolerance."
                    if difference <= policy.amount_absolute_tolerance
                    else "Invoice subtotal differs from the sum of usable line totals."
                ),
                evidence=list(invoice.subtotal.evidence),
            )
        )

    tax = _numeric_value(invoice.tax)
    if tax is None:
        checks.append(
            _check(
                code=ReasonCode.INVOICE_SCHEMA_INCOMPLETE,
                passed=False,
                expected="tax present",
                actual=None,
                tolerance=None,
                message="Invoice tax is missing or ambiguous.",
                evidence=list(invoice.tax.evidence),
            )
        )
    for label, value, field in (
        ("subtotal", subtotal, invoice.subtotal),
        ("tax", tax, invoice.tax),
        ("total", total, invoice.total),
    ):
        if value is not None and value < 0:
            checks.append(
                _check(
                    code=ReasonCode.NEGATIVE_AMOUNT,
                    passed=False,
                    expected=f"non-negative {label}",
                    actual=value,
                    tolerance=None,
                    message=f"Invoice {label} is negative and requires review.",
                    evidence=list(field.evidence),
                )
            )

    if subtotal is not None and tax is not None and total is not None:
        expected_total = subtotal + tax
        difference = abs(expected_total - total)
        checks.append(
            _check(
                code=ReasonCode.INVOICE_TOTAL_MISMATCH,
                passed=difference <= policy.amount_absolute_tolerance,
                expected=expected_total,
                actual=total,
                tolerance=policy.amount_absolute_tolerance,
                message=(
                    "Invoice total is within tolerance."
                    if difference <= policy.amount_absolute_tolerance
                    else "Invoice total differs from subtotal plus tax."
                ),
                evidence=_evidence(invoice.subtotal, invoice.tax, invoice.total),
            )
        )
    return checks
