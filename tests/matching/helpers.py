import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    TextSource,
)
from invoiceops.schemas.matching import (
    PurchaseOrderLineRead,
    PurchaseOrderRead,
)


def extracted[T](value: T) -> ExtractedField[T]:
    return ExtractedField[T](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=[
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2),
                text="synthetic",
                source=TextSource.EMBEDDED,
            )
        ],
        rule_id="synthetic.test",
    )


def missing[T]() -> ExtractedField[T]:
    return ExtractedField[T](value=None, status=ExtractionStatus.MISSING, evidence=[])


def invoice_line(
    description: str,
    quantity: str,
    unit_price: str,
    line_total: str,
) -> InvoiceLine:
    return InvoiceLine(
        description=extracted(description),
        quantity=extracted(Decimal(quantity)),
        unit_price=extracted(Decimal(unit_price)),
        line_total=extracted(Decimal(line_total)),
    )


def invoice(
    *,
    currency: str = "INR",
    subtotal: str = "1200.00",
    tax: str = "216.00",
    total: str = "1416.00",
    lines: list[InvoiceLine] | None = None,
) -> Invoice:
    return Invoice(
        invoice_number=extracted("SYN-123"),
        invoice_date=extracted(date(2026, 9, 21)),
        currency=extracted(currency),
        subtotal=extracted(Decimal(subtotal)),
        tax=extracted(Decimal(tax)),
        total=extracted(Decimal(total)),
        line_items=lines
        or [
            invoice_line("Industrial Filter", "2", "500.00", "1000.00"),
            invoice_line("Mounting Bracket", "4", "50.00", "200.00"),
        ],
    )


def purchase_order(
    *,
    currency: str = "INR",
    lines: list[tuple[str, str, str, str]] | None = None,
) -> PurchaseOrderRead:
    po_id = uuid.uuid4()
    source_lines = lines or [
        ("1", "Industrial Filter", "2", "500.00"),
        ("2", "Mounting Bracket", "4", "50.00"),
    ]
    return PurchaseOrderRead(
        id=po_id,
        external_po_number="PO-SYN-1",
        vendor_name="Synthetic Vendor",
        currency=currency,
        created_at=datetime.now(UTC),
        lines=[
            PurchaseOrderLineRead(
                id=uuid.uuid4(),
                purchase_order_id=po_id,
                line_number=line_number,
                description=description,
                ordered_quantity=Decimal(quantity),
                unit_price=Decimal(unit_price),
            )
            for line_number, description, quantity, unit_price in source_lines
        ],
    )
