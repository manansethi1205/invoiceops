from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from invoiceops.cases.service import CaseConflictError, PayableCaseService
from invoiceops.extraction.supporting import (
    SUPPORTING_EXTRACTOR_NAME,
    SUPPORTING_EXTRACTOR_VERSION,
    SUPPORTING_SCHEMA_VERSION,
)
from invoiceops.ingestion.service import UploadCommand
from invoiceops.models import CaseConfirmation, PurchaseOrder, SupportingExtractionRun
from invoiceops.schemas.cases import (
    CaseCreate,
    DocumentRole,
    ExtractedGoodsReceipt,
    ExtractedGoodsReceiptLine,
    ExtractedPurchaseOrder,
    ExtractedPurchaseOrderLine,
    PurchaseOrderConfirmation,
    PurchaseOrderConfirmationValues,
    SupportingExtractionStatus,
)
from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    TextSource,
)
from invoiceops.schemas.matching import PurchaseOrderLineCreate


def extracted[T](value: T) -> ExtractedField[T]:
    return ExtractedField[T](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=[
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2),
                text=str(value),
                source=TextSource.EMBEDDED,
            )
        ],
        rule_id="synthetic.test.v1",
    )


@pytest.mark.parametrize(
    ("confirmed_amount", "amount_supplied", "reason", "expected_corrections"),
    [
        ("20", True, None, []),
        ("20.00", True, None, []),
        ("21.00", True, "Printed amount corrected after review", ["lines", "lines.0.line_total"]),
        (None, True, "Printed amount unavailable", ["lines", "lines.0.line_total"]),
        (None, False, None, []),
    ],
)
def test_confirmation_is_atomic_immutable_and_idempotent(
    db_session_factory: object,
    object_store: object,
    dispatcher: object,
    confirmed_amount: str | None,
    amount_supplied: bool,
    reason: str | None,
    expected_corrections: list[str],
) -> None:
    factory = db_session_factory
    with factory() as session:  # type: ignore[operator]
        service = PayableCaseService(
            session,
            object_store=object_store,  # type: ignore[arg-type]
            dispatcher=dispatcher,  # type: ignore[arg-type]
            max_upload_bytes=1024,
        )
        payable_case = service.create(CaseCreate(idempotency_key="confirm-case")).payable_case
        attachment_result = service.attach(
            payable_case.id,
            role=DocumentRole.PURCHASE_ORDER,
            idempotency_key="attach-po",
            expected_case_version=payable_case.version,
            command=UploadCommand(
                filename="po.pdf",
                content_type="application/pdf",
                body=b"%PDF- synthetic purchase order",
            ),
        )
        attachment = attachment_result.attachment
        output = ExtractedPurchaseOrder(
            po_number=extracted("PO-1"),
            issue_date=extracted(date(2026, 9, 30)),
            vendor=extracted("Synthetic Supplier"),
            buyer=extracted("Synthetic Buyer"),
            currency=extracted("INR"),
            subtotal=extracted(Decimal("20.00")),
            tax=extracted(Decimal("2.00")),
            total=extracted(Decimal("22.00")),
            line_items=[
                ExtractedPurchaseOrderLine(
                    line_number=extracted("1"),
                    description=extracted("Widgets"),
                    ordered_quantity=extracted(Decimal("2")),
                    unit_price=extracted(Decimal("10.00")),
                    line_total=extracted(Decimal("20.00")),
                )
            ],
        )
        run = SupportingExtractionRun(
            document_id=attachment.document_id,
            role=DocumentRole.PURCHASE_ORDER,
            extractor_name=SUPPORTING_EXTRACTOR_NAME,
            extractor_version=SUPPORTING_EXTRACTOR_VERSION,
            schema_version=SUPPORTING_SCHEMA_VERSION,
            status=SupportingExtractionStatus.SUCCEEDED,
            output_json=output.model_dump(mode="json"),
            used_ocr=False,
        )
        session.add(run)
        session.commit()
        command = PurchaseOrderConfirmation(
            expected_case_version=attachment_result.case.version,
            extraction_run_id=run.id,
            extractor_version=run.extractor_version,
            confirmed=PurchaseOrderConfirmationValues(
                external_po_number="PO-1",
                vendor_name="Synthetic Supplier",
                buyer_name="Synthetic Buyer",
                currency="INR",
                issue_date=date(2026, 9, 30),
                subtotal="20.00",
                tax="2.00",
                total="22.00",
                lines=[
                    PurchaseOrderLineCreate(
                        line_number="1",
                        description="Widgets",
                        ordered_quantity="2",
                        unit_price="10.00",
                        **({"line_total": confirmed_amount} if amount_supplied else {}),
                    )
                ],
            ),
            correction_reason=reason,
            idempotency_key="confirm-po",
        )

        if expected_corrections:
            without_reason = command.model_copy(update={"correction_reason": None})
            with pytest.raises(CaseConflictError, match="Corrected values require a reason"):
                service.confirm_purchase_order(payable_case.id, without_reason)

        first = service.confirm_purchase_order(payable_case.id, command)
        repeated = service.confirm_purchase_order(payable_case.id, command)

        assert first.id == repeated.id
        assert first.corrected_fields == expected_corrections
        stored_confirmation = session.get(CaseConfirmation, first.id)
        assert stored_confirmation is not None
        assert stored_confirmation.confirmed_json["lines"][0]["line_total"] == confirmed_amount
        stored_po = session.get(PurchaseOrder, first.canonical_record_id)
        assert stored_po is not None
        assert stored_po.lines[0].line_total == (
            None if confirmed_amount is None else Decimal(confirmed_amount)
        )
        stale = command.model_copy(update={"idempotency_key": "new-attempt"})
        with pytest.raises(CaseConflictError) as conflict:
            service.confirm_purchase_order(payable_case.id, stale)
        assert conflict.value.code == "STALE_CASE_VERSION"
        assert session.scalar(select(func.count(PurchaseOrder.id))) == 1
        stored_run = session.get(SupportingExtractionRun, run.id)
        assert stored_run is not None
        assert stored_run.output_json == output.model_dump(mode="json")


def test_unchanged_receipt_date_does_not_require_correction_reason() -> None:
    output = ExtractedGoodsReceipt(
        receipt_number=extracted("GR-1"),
        referenced_po_number=extracted("PO-1"),
        received_date=extracted(date(2026, 9, 30)),
        supplier=extracted("Synthetic Supplier"),
        line_items=[
            ExtractedGoodsReceiptLine(
                description=extracted("Widgets"),
                received_quantity=extracted(Decimal("2")),
                accepted_quantity=extracted(Decimal("2")),
                rejected_quantity=extracted(Decimal("0")),
            )
        ],
    )
    confirmed: dict[str, object] = {
        "external_receipt_number": "GR-1",
        "referenced_po_number": "PO-1",
        "received_at": "2026-09-30T00:00:00Z",
        "supplier": "Synthetic Supplier",
        "lines": [
            {
                "purchase_order_line_number": "1",
                "description": "Widgets",
                "received_quantity": "2",
                "accepted_quantity": "2",
                "rejected_quantity": "0",
            }
        ],
    }
    assert PayableCaseService._receipt_corrected_fields(output, confirmed) == []
    confirmed["received_at"] = "2026-10-01T00:00:00Z"
    assert PayableCaseService._receipt_corrected_fields(output, confirmed) == ["received_at"]
