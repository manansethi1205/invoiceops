import uuid
from datetime import UTC, datetime
from decimal import Decimal

from invoiceops.matching.three_way import match_invoice_three_way
from invoiceops.schemas.matching import (
    MatchDecision,
    PurchaseOrderRead,
    ReasonCode,
    ThreeWayMatchingPolicy,
)
from invoiceops.schemas.three_way import (
    ReceiptLineContextRead,
    ReceiptQuantityRead,
    ThreeWayContextSnapshot,
)
from tests.matching.helpers import invoice, invoice_line, purchase_order


def _context(
    *,
    received: tuple[str, str] = ("2", "4"),
    prior: tuple[str, str] = ("0", "0"),
    reversed_first: bool = False,
    after_invoice: bool = False,
) -> tuple[PurchaseOrderRead, ThreeWayContextSnapshot]:
    po = purchase_order()
    timestamp = datetime(2026, 9, 22 if after_invoice else 20, tzinfo=UTC)
    lines = []
    for index, po_line in enumerate(po.lines):
        quantity = Decimal(received[index])
        active = (
            []
            if quantity == 0 or (index == 0 and reversed_first)
            else [
                ReceiptQuantityRead(
                    receipt_id=uuid.uuid4(),
                    accepted_quantity=format(quantity, "f"),
                    received_at=timestamp,
                )
            ]
        )
        prior_quantity = Decimal(prior[index])
        lines.append(
            ReceiptLineContextRead(
                purchase_order_line_id=po_line.id,
                ordered_quantity=format(po_line.ordered_quantity, "f"),
                active_receipts=active,
                reversed_receipts=[
                    ReceiptQuantityRead(
                        receipt_id=uuid.uuid4(),
                        accepted_quantity=format(quantity, "f"),
                        received_at=timestamp,
                    )
                ]
                if index == 0 and reversed_first
                else [],
                reversal_ids=[uuid.uuid4()] if index == 0 and reversed_first else [],
                effective_received_quantity=format(quantity if active else Decimal("0"), "f"),
                previously_allocated_quantity=format(prior_quantity, "f"),
                available_quantity=format(
                    (quantity if active else Decimal("0")) - prior_quantity, "f"
                ),
            )
        )
    return po, ThreeWayContextSnapshot(
        purchase_order_id=po.id,
        policy_version="three-way-v1",
        lines=lines,
    )


def _codes(
    *,
    received: tuple[str, str] = ("2", "4"),
    prior: tuple[str, str] = ("0", "0"),
    reversed_first: bool = False,
    after_invoice: bool = False,
) -> tuple[MatchDecision, set[ReasonCode], int]:
    po, context = _context(
        received=received,
        prior=prior,
        reversed_first=reversed_first,
        after_invoice=after_invoice,
    )
    result, allocations = match_invoice_three_way(invoice(), po, context, ThreeWayMatchingPolicy())
    return result.decision, set(result.reason_codes), len(allocations)


def test_complete_receipt_matches_and_produces_allocations() -> None:
    decision, codes, allocation_count = _codes()
    assert decision == MatchDecision.MATCHED
    assert codes == set()
    assert allocation_count == 2


def test_missing_receipts_and_missing_receipt_line_are_distinct() -> None:
    _, none_codes, _ = _codes(received=("0", "0"))
    _, partial_codes, _ = _codes(received=("2", "0"))
    assert ReasonCode.NO_GOODS_RECEIPT in none_codes
    assert ReasonCode.RECEIPT_LINE_MISSING in partial_codes


def test_reversal_and_post_invoice_receipt_are_explainable() -> None:
    _, reversed_codes, _ = _codes(reversed_first=True)
    _, late_codes, _ = _codes(after_invoice=True)
    assert ReasonCode.GOODS_RECEIPT_REVERSED in reversed_codes
    assert ReasonCode.RECEIPT_AFTER_INVOICE in late_codes


def test_over_receipt_and_cumulative_over_invoice_route_to_review() -> None:
    _, receipt_codes, _ = _codes(received=("3", "4"))
    _, cumulative_codes, allocation_count = _codes(prior=("1", "0"))
    assert ReasonCode.RECEIVED_QUANTITY_EXCEEDS_ORDERED in receipt_codes
    assert ReasonCode.CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED in cumulative_codes
    assert allocation_count == 0


def test_unit_price_and_line_amount_tolerances_use_invoice_quantity() -> None:
    po, context = _context()
    price_failure = invoice(
        lines=[
            invoice_line("Industrial Filter", "2", "505.01", "1000.00"),
            invoice_line("Mounting Bracket", "4", "50.00", "200.00"),
        ]
    )
    result, allocations = match_invoice_three_way(
        price_failure, po, context, ThreeWayMatchingPolicy()
    )
    assert ReasonCode.THREE_WAY_UNIT_PRICE_MISMATCH in result.reason_codes
    assert allocations == []

    amount_failure = invoice(
        subtotal="1200.03",
        total="1416.03",
        lines=[
            invoice_line("Industrial Filter", "2", "500.00", "1000.03"),
            invoice_line("Mounting Bracket", "4", "50.00", "200.00"),
        ],
    )
    result, _ = match_invoice_three_way(amount_failure, po, context, ThreeWayMatchingPolicy())
    assert ReasonCode.THREE_WAY_LINE_AMOUNT_MISMATCH in result.reason_codes


def test_quantity_tolerance_boundary_passes_and_immediately_outside_fails() -> None:
    po, context = _context()
    policy = ThreeWayMatchingPolicy(quantity_absolute_tolerance=Decimal("0.01"))
    boundary = invoice(
        subtotal="1205.00",
        total="1421.00",
        lines=[
            invoice_line("Industrial Filter", "2.01", "500.00", "1005.00"),
            invoice_line("Mounting Bracket", "4", "50.00", "200.00"),
        ],
    )
    result, _ = match_invoice_three_way(boundary, po, context, policy)
    assert ReasonCode.INVOICE_QUANTITY_EXCEEDS_RECEIVED not in result.reason_codes

    outside = invoice(
        subtotal="1205.005",
        total="1421.005",
        lines=[
            invoice_line("Industrial Filter", "2.01001", "500.00", "1005.005"),
            invoice_line("Mounting Bracket", "4", "50.00", "200.00"),
        ],
    )
    result, _ = match_invoice_three_way(outside, po, context, policy)
    assert ReasonCode.INVOICE_QUANTITY_EXCEEDS_RECEIVED in result.reason_codes


def test_partial_invoice_can_be_disabled_by_versioned_policy() -> None:
    po, context = _context(received=("2", "4"))
    partial = invoice(
        subtotal="700",
        tax="0",
        total="700",
        lines=[
            invoice_line("Industrial Filter", "1", "500", "500"),
            invoice_line("Mounting Bracket", "4", "50", "200"),
        ],
    )
    result, allocations = match_invoice_three_way(
        partial,
        po,
        context,
        ThreeWayMatchingPolicy(allow_partial_invoice=False),
    )
    assert ReasonCode.QUANTITY_MISMATCH in result.reason_codes
    assert allocations == []
