from typing import Protocol

from invoiceops.extraction.header_rules import (
    extract_currency,
    extract_invoice_date,
    extract_invoice_number,
    extract_subtotal,
    extract_tax,
    extract_total,
)
from invoiceops.extraction.layout import reconstruct_lines
from invoiceops.extraction.line_item_rules import extract_line_items
from invoiceops.extraction.version import EXTRACTOR_NAME, EXTRACTOR_VERSION
from invoiceops.schemas.extraction import DocumentText, Invoice


class InvoiceExtractor(Protocol):
    name: str
    version: str

    def extract(self, document: DocumentText) -> Invoice: ...


class DeterministicInvoiceExtractor:
    name = EXTRACTOR_NAME
    version = EXTRACTOR_VERSION

    def extract(self, document: DocumentText) -> Invoice:
        lines = reconstruct_lines(document)
        return Invoice(
            invoice_number=extract_invoice_number(lines),
            invoice_date=extract_invoice_date(lines),
            currency=extract_currency(lines),
            subtotal=extract_subtotal(lines),
            tax=extract_tax(lines),
            total=extract_total(lines),
            line_items=extract_line_items(document),
        )
