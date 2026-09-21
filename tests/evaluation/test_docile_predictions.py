from datetime import date
from decimal import Decimal

from invoiceops.evaluation.docile_predictions import invoice_to_docile_predictions
from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    TextSource,
)


def _evidence(page: int, x0: float, x1: float) -> EvidenceSpan:
    return EvidenceSpan(
        page=page,
        bbox=BoundingBox(x0=x0, y0=0.1, x1=x1, y1=0.2),
        text="sensitive source text",
        source=TextSource.OCR,
    )


def _field(value: object, evidence: list[EvidenceSpan]) -> ExtractedField[object]:
    return ExtractedField[object](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=evidence,
        rule_id="test.rule.v1",
    )


def _invoice(*, cross_page_total: bool = False) -> Invoice:
    total_evidence = [_evidence(0, 0.1, 0.2), _evidence(1 if cross_page_total else 0, 0.3, 0.4)]
    return Invoice(
        invoice_number=_field("INV-1", [_evidence(0, 0.1, 0.2), _evidence(0, 0.3, 0.4)]),
        invoice_date=_field(date(2026, 9, 20), [_evidence(0, 0.1, 0.2)]),
        currency=_field("USD", [_evidence(0, 0.1, 0.2)]),
        subtotal=_field(Decimal("10"), [_evidence(0, 0.1, 0.2)]),
        tax=_field(Decimal("2"), [_evidence(0, 0.1, 0.2)]),
        total=_field(Decimal("12"), total_evidence),
        line_items=[
            InvoiceLine(
                description=_field("Filter", [_evidence(0, 0.1, 0.2)]),
                quantity=_field(Decimal("2"), [_evidence(0, 0.3, 0.4)]),
                unit_price=_field(Decimal("5"), [_evidence(0, 0.5, 0.6)]),
                line_total=_field(Decimal("10"), [_evidence(0, 0.7, 0.8)]),
            )
        ],
    )


def test_predictions_union_same_page_evidence_and_omit_unsupported_fields() -> None:
    kile, lir = invoice_to_docile_predictions(_invoice())

    document_id = next(item for item in kile if item.fieldtype == "document_id")
    assert document_id.bbox == (0.1, 0.1, 0.4, 0.2)
    assert all(item.line_item_id is None for item in kile)
    assert {item.fieldtype for item in lir} == {
        "line_item_description",
        "line_item_quantity",
    }
    assert {item.line_item_id for item in lir} == {0}
    assert "sensitive source text" not in {item.text for item in kile + lir}


def test_cross_page_evidence_is_omitted_safely() -> None:
    kile, _ = invoice_to_docile_predictions(_invoice(cross_page_total=True))
    assert "amount_total_gross" not in {item.fieldtype for item in kile}
