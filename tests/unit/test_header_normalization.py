from datetime import date
from decimal import Decimal

import pytest

from invoiceops.extraction.normalization import (
    normalize_currency,
    normalize_identifier,
    normalize_whitespace,
    parse_invoice_date,
    parse_money,
)


def test_identifier_and_whitespace_normalization() -> None:
    assert normalize_whitespace("  INV-2026   0042 \n") == "INV-2026 0042"
    assert normalize_identifier("Inv-2026 / 0042") == "INV20260042"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("19/09/2026", date(2026, 9, 19)),
        ("19-09-2026", date(2026, 9, 19)),
        ("2026-09-19", date(2026, 9, 19)),
        ("19 Sep 2026", date(2026, 9, 19)),
        ("September 19, 2026", date(2026, 9, 19)),
        ("09/19/2026", None),
    ],
)
def test_explicit_invoice_date_formats(raw: str, expected: date | None) -> None:
    assert parse_invoice_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,180.00", Decimal("1180.00")),
        ("₹1,180.00", Decimal("1180.00")),
        ("INR 1180", Decimal("1180")),
        ("1 180,00", Decimal("1180.00")),
        ("(250.00)", Decimal("-250.00")),
        ("not money", None),
    ],
)
def test_money_is_parsed_without_float(raw: str, expected: Decimal | None) -> None:
    result = parse_money(raw)
    assert result == expected
    assert result is None or isinstance(result, Decimal)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("inr", "INR"), ("Indian Rupees", "INR"), ("₹", "INR"), ("€", "EUR"), ("$", None)],
)
def test_currency_normalization_does_not_guess_dollars(raw: str, expected: str | None) -> None:
    assert normalize_currency(raw) == expected
