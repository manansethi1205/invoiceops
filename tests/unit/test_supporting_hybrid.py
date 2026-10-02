"""Synthetic-only routing and evidence-grounding safety tests."""

from datetime import date

import pytest

from invoiceops.extraction.hybrid.schemas import CandidateField
from invoiceops.extraction.supporting import extract_goods_receipt, extract_purchase_order
from invoiceops.extraction.supporting_hybrid import (
    DeliveryNoteCandidate,
    GoodsReceiptCandidate,
    PurchaseOrderCandidate,
    PurchaseOrderLineCandidate,
    SupportingFusionState,
    SupportingRouteReason,
    fuse_supporting,
    route_supporting,
)
from invoiceops.schemas.cases import DocumentRole
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus
from tests.unit.test_supporting_extraction import document_from_rows


def field(value: str | None = None, *, quote: str | None = None, page: int = 0) -> CandidateField:
    return CandidateField(
        raw_value=value,
        page=page if value is not None else None,
        evidence_quote=quote if quote is not None else value,
        confidence=0.99 if value is not None else None,
    )


def po_candidate(**overrides: CandidateField) -> PurchaseOrderCandidate:
    fields = {
        "po_number": field(),
        "issue_date": field(),
        "vendor": field(),
        "buyer": field(),
        "currency": field(),
        "subtotal": field(),
        "tax": field(),
        "total": field(),
    }
    fields.update(overrides)
    return PurchaseOrderCandidate(**fields, line_items=[])


def test_routes_only_typed_insufficiency_and_never_uses_confidence_as_grounding() -> None:
    complete_doc = document_from_rows(
        [
            [("PO", 0.05), ("No:", 0.14), ("PO-100", 0.25)],
            [("Order", 0.05), ("Date:", 0.15), ("30/09/2026", 0.3)],
            [("Currency:", 0.05), ("INR", 0.3)],
            [
                ("Line", 0.01),
                ("Description", 0.1),
                ("Qty", 0.5),
                ("Unit", 0.62),
                ("Price", 0.68),
                ("Amount", 0.85),
            ],
            [("1", 0.01), ("Widgets", 0.1), ("2", 0.51), ("10.00", 0.7), ("20.00", 0.86)],
        ]
    )
    complete = extract_purchase_order(complete_doc)
    assert not route_supporting(complete, complete_doc, DocumentRole.PURCHASE_ORDER).invoke_model

    missing_doc = document_from_rows([[("Reference", 0.05), ("ABC-100", 0.3)]])
    missing = extract_purchase_order(missing_doc)
    routing = route_supporting(missing, missing_doc, DocumentRole.PURCHASE_ORDER)
    assert SupportingRouteReason.REQUIRED_FIELD_MISSING in routing.reasons
    fused = fuse_supporting(
        missing, po_candidate(po_number=field("ABC-100", quote="ABC-100")), missing_doc
    )
    assert fused.output.po_number.value == "ABC-100"
    assert fused.output.po_number.evidence
    assert fused.outcomes["po_number"] == SupportingFusionState.FILLED
    assert missing.po_number.value is None


def test_wrong_page_unsupported_quote_and_unsupported_value_abstain() -> None:
    doc = document_from_rows([[("Reference", 0.05), ("ABC-100", 0.3)]])
    baseline = extract_purchase_order(doc)
    for proposed in (
        field("ABC-100", page=1),
        field("ABC-100", quote="not on this page"),
        field("ABC-999", quote="ABC-100"),
    ):
        fused = fuse_supporting(baseline, po_candidate(po_number=proposed), doc)
        assert fused.output.po_number.status == ExtractionStatus.MISSING
        assert fused.outcomes["po_number"] == SupportingFusionState.UNGROUNDED


def test_grounded_conflict_preserves_both_and_abstains() -> None:
    doc = document_from_rows(
        [
            [("PO", 0.05), ("No:", 0.14), ("PO-100", 0.3)],
            [("Reference", 0.05), ("ABC-200", 0.3)],
        ]
    )
    baseline = extract_purchase_order(doc)
    fused = fuse_supporting(
        baseline, po_candidate(po_number=field("ABC-200", quote="ABC-200")), doc
    )
    assert baseline.po_number.value == "PO-100"
    assert fused.output.po_number.status == ExtractionStatus.AMBIGUOUS
    assert fused.output.po_number.value is None
    assert len(fused.output.po_number.evidence) == 2
    assert fused.outcomes["po_number"] == SupportingFusionState.CONFLICT_ABSTAINED


def test_receipt_has_role_specific_date_and_quantity_routing() -> None:
    doc = document_from_rows(
        [
            [("Goods", 0.05), ("Receipt", 0.13), ("GR-1", 0.3)],
            [("Delivery", 0.05), ("Date:", 0.15), ("01/10/2026", 0.3)],
            [("PO", 0.05), ("No:", 0.14), ("PO-100", 0.3)],
        ]
    )
    baseline = extract_goods_receipt(doc)
    routing = route_supporting(baseline, doc, DocumentRole.GOODS_RECEIPT)
    assert SupportingRouteReason.NO_LINE_ITEMS in routing.reasons
    candidate = GoodsReceiptCandidate(
        receipt_number=field(),
        referenced_po_number=field(),
        received_date=field("01/10/2026", quote="01/10/2026"),
        supplier=field(),
        line_items=[],
    )
    fused = fuse_supporting(baseline, candidate, doc)
    assert fused.output.received_date.value == date(2026, 10, 1)
    assert fused.output.line_items == []
    assert route_supporting(baseline, doc, DocumentRole.DELIVERY_NOTE).invoke_model
    with pytest.raises(ValueError, match="role does not match"):
        route_supporting(baseline, doc, DocumentRole.PURCHASE_ORDER)
    delivery_candidate = DeliveryNoteCandidate.model_validate(candidate.model_dump())
    assert isinstance(delivery_candidate, DeliveryNoteCandidate)
    assert fuse_supporting(baseline, delivery_candidate, doc).output.received_date.value == date(
        2026, 10, 1
    )


def test_receipt_unassociated_quantity_and_ocr_missing_field_have_typed_reasons() -> None:
    doc = document_from_rows([
        [("Goods", .05), ("Receipt", .13), ("GR-1", .3)],
        [("Description", .05), ("Received", .5), ("Accepted", .68)],
        [("Widgets", .05), ("2", .5), ("2", .68)],
    ])
    baseline = extract_goods_receipt(doc)
    assert baseline.line_items
    missing = ExtractedField[object](value=None, status=ExtractionStatus.MISSING, evidence=[])
    incomplete = baseline.model_copy(update={
        "line_items": [baseline.line_items[0].model_copy(update={"received_quantity": missing})]
    })
    routing = route_supporting(incomplete, doc, DocumentRole.GOODS_RECEIPT)
    assert SupportingRouteReason.QUANTITY_ASSOCIATION_INCOMPLETE in routing.reasons
    ocr_doc = doc.model_copy(update={"used_ocr": True})
    missing_date = incomplete.model_copy(update={"received_date": missing})
    assert SupportingRouteReason.OCR_REQUIRED_FIELD in route_supporting(
        missing_date, ocr_doc, DocumentRole.GOODS_RECEIPT
    ).reasons


def test_numeric_value_from_wrong_table_column_is_rejected() -> None:
    doc = document_from_rows([
        [("PO", .05), ("No:", .14), ("PO-100", .3)],
        [("Description", .1), ("Qty", .5), ("Unit", .62), ("Price", .68),
         ("Amount", .85)],
        [("Widgets", .1), ("2", .51), ("10.00", .7), ("20.00", .86)],
    ])
    baseline = extract_purchase_order(doc)
    candidate = po_candidate().model_copy(update={
        "line_items": [PurchaseOrderLineCandidate(
            line_number=field(), description=field("Widgets"),
            ordered_quantity=field("20", quote="20.00"),
            unit_price=field("10.00"), line_total=field("20.00"),
        )],
    })
    fused = fuse_supporting(baseline, candidate, doc)
    assert fused.grounding["line_items.0.ordered_quantity"] == "VALUE_NORMALIZATION_FAILED"
    assert (
        fused.output.line_items[0].ordered_quantity.value
        == baseline.line_items[0].ordered_quantity.value
    )


def test_conflicting_po_totals_route_to_model_but_are_never_reconciled_by_it() -> None:
    doc = document_from_rows([
        [("PO", .05), ("No:", .14), ("PO-100", .3)],
        [("Order", .05), ("Date:", .15), ("30/09/2026", .3)],
        [("Currency:", .05), ("INR", .3)],
        [("Subtotal", .05), ("20.00", .85)],
        [("Tax", .05), ("Total", .15), ("2.00", .85)],
        [("Grand", .05), ("Total", .15), ("99.00", .85)],
    ])
    baseline = extract_purchase_order(doc)
    assert SupportingRouteReason.TOTAL_CONFLICT in route_supporting(
        baseline, doc, DocumentRole.PURCHASE_ORDER
    ).reasons
    fused = fuse_supporting(
        baseline, po_candidate(total=field("20.00", quote="Subtotal 20.00")), doc
    )
    assert fused.output.total.value == baseline.total.value
    assert fused.outcomes["total"] == SupportingFusionState.UNGROUNDED
    assert baseline.total.value is not None
