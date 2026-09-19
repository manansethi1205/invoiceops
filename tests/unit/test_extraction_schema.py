from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    TextSource,
)


def evidence(text: str) -> EvidenceSpan:
    return EvidenceSpan(
        page=0,
        bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.4, y1=0.2),
        text=text,
        source=TextSource.EMBEDDED,
    )


def missing_field[T]() -> ExtractedField[T]:
    return ExtractedField[T](value=None, status=ExtractionStatus.MISSING, evidence=[])


def test_invoice_contract_keeps_typed_values_and_evidence() -> None:
    invoice = Invoice(
        invoice_number=ExtractedField[str](
            value="INV-42",
            status=ExtractionStatus.EXTRACTED,
            evidence=[evidence("Invoice Number: INV-42")],
            rule_id="test.invoice-number.v1",
        ),
        invoice_date=ExtractedField[date](
            value=date(2026, 9, 19),
            status=ExtractionStatus.EXTRACTED,
            evidence=[evidence("Invoice Date: 19/09/2026")],
        ),
        currency=ExtractedField[str](
            value="INR",
            status=ExtractionStatus.EXTRACTED,
            evidence=[evidence("Currency: INR")],
        ),
        subtotal=missing_field(),
        tax=missing_field(),
        total=ExtractedField[Decimal](
            value=Decimal("1180.00"),
            status=ExtractionStatus.EXTRACTED,
            evidence=[evidence("Total: 1180.00")],
        ),
        line_items=[],
    )

    assert invoice.total.value == Decimal("1180.00")
    assert invoice.invoice_number.evidence[0].page == 0


def test_extracted_field_rejects_missing_provenance() -> None:
    with pytest.raises(ValidationError, match="must contain evidence"):
        ExtractedField[str](
            value="INV-42",
            status=ExtractionStatus.EXTRACTED,
            evidence=[],
        )
