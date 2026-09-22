from datetime import date
from decimal import Decimal

import pytest

from invoiceops.extraction.hybrid.router import route_extraction
from invoiceops.extraction.hybrid.schemas import RoutingReason
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    OcrReason,
    PageText,
    TextSource,
)


def field(value: object | None, status: ExtractionStatus | None = None) -> ExtractedField[object]:
    effective = status or (
        ExtractionStatus.MISSING if value is None else ExtractionStatus.EXTRACTED
    )
    return ExtractedField[object](
        value=value,
        status=effective,
        evidence=[]
        if effective != ExtractionStatus.EXTRACTED
        else [
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0, y0=0, x1=0.1, y1=0.1),
                text="synthetic",
                source=TextSource.EMBEDDED,
            )
        ],
    )


def complete_invoice() -> Invoice:
    return Invoice(
        invoice_number=field("INV-1"),
        invoice_date=field(date(2026, 9, 21)),
        currency=field("INR"),
        subtotal=field(Decimal("20")),
        tax=field(Decimal("2")),
        total=field(Decimal("22")),
        line_items=[
            InvoiceLine(
                description=field("Part"),
                quantity=field(Decimal("2")),
                unit_price=field(Decimal("10")),
                line_total=field(Decimal("20")),
            )
        ],
    )


def document(*sources: TextSource) -> DocumentText:
    return DocumentText(
        pages=[
            PageText(
                page=index,
                width=100,
                height=100,
                source=source,
                ocr_reason=OcrReason.NO_EMBEDDED_TEXT
                if source == TextSource.OCR
                else OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=[],
            )
            for index, source in enumerate(sources)
        ],
        used_ocr=TextSource.OCR in sources,
    )


def test_complete_digital_invoice_declines_provider() -> None:
    decision = route_extraction(complete_invoice(), document(TextSource.EMBEDDED))
    assert decision.invoke_vlm is False
    assert decision.reasons == []
    assert decision.deterministic_completeness == 1
    assert decision.critical_field_completeness == 1
    assert decision.complete_line_item_ratio == 1


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("critical_missing", RoutingReason.CRITICAL_FIELD_MISSING),
        ("critical_ambiguous", RoutingReason.CRITICAL_FIELD_AMBIGUOUS),
        ("no_lines", RoutingReason.NO_LINE_ITEMS),
        ("incomplete_line", RoutingReason.INCOMPLETE_LINE_ITEMS),
        ("header_arithmetic", RoutingReason.HEADER_ARITHMETIC_CONTRADICTION),
        ("line_arithmetic", RoutingReason.LINE_ARITHMETIC_CONTRADICTION),
    ],
)
def test_each_quality_reason_routes(mutation: str, reason: RoutingReason) -> None:
    invoice = complete_invoice()
    if mutation == "critical_missing":
        invoice.invoice_number = field(None)  # type: ignore[assignment]
    elif mutation == "critical_ambiguous":
        invoice.total = field(None, ExtractionStatus.AMBIGUOUS)  # type: ignore[assignment]
    elif mutation == "no_lines":
        invoice.line_items = []
    elif mutation == "incomplete_line":
        invoice.line_items[0].quantity = field(None)  # type: ignore[assignment]
    elif mutation == "header_arithmetic":
        invoice.total = field(Decimal("23"))  # type: ignore[assignment]
    else:
        invoice.line_items[0].line_total = field(Decimal("21"))  # type: ignore[assignment]
    decision = route_extraction(invoice, document(TextSource.EMBEDDED))
    assert decision.invoke_vlm is True
    assert reason in decision.reasons
    assert len(decision.reasons) == len(set(decision.reasons))


def test_arithmetic_and_ocr_threshold_boundaries_are_inclusive_as_documented() -> None:
    invoice = complete_invoice()
    invoice.total = field(Decimal("22.02"))  # type: ignore[assignment]
    at_tolerance = route_extraction(invoice, document(TextSource.EMBEDDED))
    assert RoutingReason.HEADER_ARITHMETIC_CONTRADICTION not in at_tolerance.reasons
    invoice.total = field(Decimal("22.021"))  # type: ignore[assignment]
    over_tolerance = route_extraction(invoice, document(TextSource.EMBEDDED))
    assert RoutingReason.HEADER_ARITHMETIC_CONTRADICTION in over_tolerance.reasons

    half_ocr = route_extraction(
        complete_invoice(), document(TextSource.OCR, TextSource.EMBEDDED), ocr_heavy_page_ratio=0.5
    )
    assert RoutingReason.OCR_HEAVY_DOCUMENT in half_ocr.reasons
