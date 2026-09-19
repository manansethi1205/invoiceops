from datetime import date
from decimal import Decimal

from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import ExtractionStatus
from tests.synthetic_documents import generated_invoice_pdf


def test_generated_digital_pdf_extracts_typed_headers_with_evidence() -> None:
    document_text = DocumentTextExtractor().extract(generated_invoice_pdf(), "application/pdf")

    invoice = DeterministicInvoiceExtractor().extract(document_text)

    assert invoice.invoice_number.value == "SYN-12345"
    assert invoice.invoice_date.value == date(2026, 9, 19)
    assert invoice.currency.value == "INR"
    assert invoice.subtotal.value == Decimal("1200.00")
    assert invoice.tax.value == Decimal("216.00")
    assert invoice.total.value == Decimal("1416.00")
    assert len(invoice.line_items) == 2
    for field in (
        invoice.invoice_number,
        invoice.invoice_date,
        invoice.currency,
        invoice.subtotal,
        invoice.tax,
        invoice.total,
    ):
        assert field.status == ExtractionStatus.EXTRACTED
        assert field.evidence
        assert field.rule_id is not None
        assert field.evidence[0].page == 0
