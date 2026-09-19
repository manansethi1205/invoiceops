from datetime import date
from decimal import Decimal

import pymupdf

from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import ExtractionStatus


def generated_invoice_pdf() -> bytes:
    document = pymupdf.open()
    try:
        page = document.new_page(width=612, height=792)
        lines = [
            "SYNTHETIC INVOICE - DEMO DATA ONLY",
            "Invoice Number: SYN-12345",
            "Invoice Date: 19/09/2026",
            "Currency: INR",
            "Subtotal: 1,000.00",
            "GST 18%: 180.00",
            "Grand Total: INR 1,180.00",
        ]
        for index, text in enumerate(lines):
            page.insert_text((72, 72 + index * 30), text, fontsize=12)
        return document.tobytes()
    finally:
        document.close()


def test_generated_digital_pdf_extracts_typed_headers_with_evidence() -> None:
    document_text = DocumentTextExtractor().extract(generated_invoice_pdf(), "application/pdf")

    invoice = DeterministicInvoiceExtractor().extract(document_text)

    assert invoice.invoice_number.value == "SYN-12345"
    assert invoice.invoice_date.value == date(2026, 9, 19)
    assert invoice.currency.value == "INR"
    assert invoice.subtotal.value == Decimal("1000.00")
    assert invoice.tax.value == Decimal("180.00")
    assert invoice.total.value == Decimal("1180.00")
    assert invoice.line_items == []
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
