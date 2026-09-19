from decimal import Decimal

from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from tests.synthetic_documents import generated_invoice_pdf


def test_generated_pdf_extracts_two_positioned_line_items() -> None:
    document = DocumentTextExtractor().extract(generated_invoice_pdf(), "application/pdf")

    invoice = DeterministicInvoiceExtractor().extract(document)

    assert len(invoice.line_items) == 2
    first, second = invoice.line_items
    assert first.description.value == "Industrial Filter"
    assert first.quantity.value == Decimal("2")
    assert first.unit_price.value == Decimal("500.00")
    assert first.line_total.value == Decimal("1000.00")
    assert second.description.value == "Mounting Bracket"
    assert second.quantity.value == Decimal("4")
    assert second.unit_price.value == Decimal("50.00")
    assert second.line_total.value == Decimal("200.00")
    assert all(
        field.evidence
        for item in invoice.line_items
        for field in (item.description, item.quantity, item.unit_price, item.line_total)
    )
