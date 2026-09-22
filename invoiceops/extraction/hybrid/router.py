from decimal import Decimal

from invoiceops.extraction.hybrid.schemas import RoutingDecision, RoutingReason
from invoiceops.schemas.extraction import DocumentText, ExtractionStatus, Invoice, InvoiceLine

HEADER_FIELDS = ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")
CRITICAL_FIELDS = ("invoice_number", "invoice_date", "currency", "total")
LINE_FIELDS = ("description", "quantity", "unit_price", "line_total")


def _is_extracted(field: object) -> bool:
    return getattr(field, "status", None) == ExtractionStatus.EXTRACTED


def _line_complete(line: InvoiceLine) -> bool:
    return all(_is_extracted(getattr(line, name)) for name in LINE_FIELDS)


def route_extraction(
    invoice: Invoice,
    document: DocumentText,
    *,
    arithmetic_tolerance: Decimal = Decimal("0.02"),
    ocr_heavy_page_ratio: float = 0.5,
) -> RoutingDecision:
    reasons: list[RoutingReason] = []
    critical = [getattr(invoice, name) for name in CRITICAL_FIELDS]
    if any(field.status == ExtractionStatus.MISSING for field in critical):
        reasons.append(RoutingReason.CRITICAL_FIELD_MISSING)
    if any(field.status == ExtractionStatus.AMBIGUOUS for field in critical):
        reasons.append(RoutingReason.CRITICAL_FIELD_AMBIGUOUS)

    if not invoice.line_items:
        reasons.append(RoutingReason.NO_LINE_ITEMS)
    elif any(not _line_complete(line) for line in invoice.line_items):
        reasons.append(RoutingReason.INCOMPLETE_LINE_ITEMS)

    if all(_is_extracted(getattr(invoice, name)) for name in ("subtotal", "tax", "total")):
        subtotal = invoice.subtotal.value
        tax = invoice.tax.value
        total = invoice.total.value
        if subtotal is not None and tax is not None and total is not None:
            if abs(subtotal + tax - total) > arithmetic_tolerance:
                reasons.append(RoutingReason.HEADER_ARITHMETIC_CONTRADICTION)

    for line in invoice.line_items:
        if all(
            _is_extracted(getattr(line, name)) for name in ("quantity", "unit_price", "line_total")
        ):
            quantity = line.quantity.value
            unit_price = line.unit_price.value
            line_total = line.line_total.value
            if quantity is not None and unit_price is not None and line_total is not None:
                if abs(quantity * unit_price - line_total) > arithmetic_tolerance:
                    reasons.append(RoutingReason.LINE_ARITHMETIC_CONTRADICTION)
                    break

    page_count = len(document.pages)
    ocr_ratio = (
        sum(page.source.value == "ocr" for page in document.pages) / page_count
        if page_count
        else 0.0
    )
    if page_count and ocr_ratio >= ocr_heavy_page_ratio:
        reasons.append(RoutingReason.OCR_HEAVY_DOCUMENT)

    header_slots = [getattr(invoice, name) for name in HEADER_FIELDS]
    line_slots = [getattr(line, name) for line in invoice.line_items for name in LINE_FIELDS]
    all_slots = header_slots + line_slots
    completeness = sum(_is_extracted(field) for field in all_slots) / len(all_slots)
    critical_completeness = sum(_is_extracted(field) for field in critical) / len(critical)
    complete_line_ratio = (
        sum(_line_complete(line) for line in invoice.line_items) / len(invoice.line_items)
        if invoice.line_items
        else 0.0
    )
    unique_reasons = list(dict.fromkeys(reasons))
    return RoutingDecision(
        invoke_vlm=bool(unique_reasons),
        reasons=unique_reasons,
        deterministic_completeness=completeness,
        critical_field_completeness=critical_completeness,
        complete_line_item_ratio=complete_line_ratio,
    )
