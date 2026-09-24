from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from invoiceops.matching.engine import match_invoice
from invoiceops.schemas.extraction import EvidenceSpan, ExtractionStatus, Invoice
from invoiceops.schemas.matching import (
    CheckSeverity,
    CheckStatus,
    MatchDecision,
    MatchingPolicy,
    MatchResult,
    MatchSummary,
    PurchaseOrderRead,
    ReasonCode,
    ThreeWayMatchingPolicy,
    ValidationCheck,
)
from invoiceops.schemas.three_way import ReceiptLineContextRead, ThreeWayContextSnapshot


@dataclass(frozen=True)
class AllocationDraft:
    purchase_order_line_id: object
    invoice_line_index: int
    quantity: Decimal


def _check(
    code: ReasonCode,
    passed: bool,
    message: str,
    *,
    line: ReceiptLineContextRead,
    invoice_index: int,
    expected: Decimal | str | None = None,
    actual: Decimal | str | None = None,
    tolerance: Decimal | None = None,
    invoice_quantity: Decimal | None = None,
    evidence: list[EvidenceSpan] | None = None,
) -> ValidationCheck:
    def serialize(value: Decimal | str | None) -> str | None:
        return format(value, "f") if isinstance(value, Decimal) else value

    return ValidationCheck(
        code=code,
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        severity=CheckSeverity.INFO if passed else CheckSeverity.ERROR,
        expected=serialize(expected),
        actual=serialize(actual),
        tolerance=serialize(tolerance),
        message=message,
        invoice_line_index=invoice_index,
        po_line_id=line.purchase_order_line_id,
        receipt_ids=[item.receipt_id for item in (*line.active_receipts, *line.reversed_receipts)],
        ordered_quantity=line.ordered_quantity,
        received_quantity=line.effective_received_quantity,
        previously_invoiced_quantity=line.previously_allocated_quantity,
        available_quantity=line.available_quantity,
        invoice_quantity=serialize(invoice_quantity),
        evidence=evidence or [],
    )


def match_invoice_three_way(
    invoice: Invoice,
    purchase_order: PurchaseOrderRead,
    context: ThreeWayContextSnapshot,
    policy: ThreeWayMatchingPolicy,
) -> tuple[MatchResult, list[AllocationDraft]]:
    base_policy = MatchingPolicy(
        amount_absolute_tolerance=policy.amount_absolute_tolerance,
        quantity_absolute_tolerance=policy.quantity_absolute_tolerance,
        unit_price_relative_tolerance=policy.unit_price_relative_tolerance,
        description_similarity_threshold=policy.description_similarity_threshold,
        ambiguity_margin=policy.ambiguity_margin,
    )
    base = match_invoice(invoice, purchase_order, base_policy)
    discarded = {
        ReasonCode.PO_LINE_UNMATCHED,
        ReasonCode.QUANTITY_MISMATCH,
        ReasonCode.UNIT_PRICE_MISMATCH,
        ReasonCode.LINE_AMOUNT_MISMATCH,
    }
    checks = [check for check in base.checks if check.code not in discarded]
    context_by_line = {line.purchase_order_line_id: line for line in context.lines}
    has_any_active_receipt = any(line.active_receipts for line in context.lines)
    po_by_line = {line.id: line for line in purchase_order.lines}
    allocations: list[AllocationDraft] = []
    invoice_date = (
        invoice.invoice_date.value
        if invoice.invoice_date.status == ExtractionStatus.EXTRACTED
        else None
    )
    for assignment in base.line_assignments:
        assignment.checks = [check for check in assignment.checks if check.code not in discarded]
        line = context_by_line[assignment.po_line_id]
        invoice_line = invoice.line_items[assignment.invoice_line_index]
        po_line = po_by_line[assignment.po_line_id]
        quantity = (
            invoice_line.quantity.value
            if invoice_line.quantity.status == ExtractionStatus.EXTRACTED
            else None
        )
        if line.reversed_receipt_ids:
            assignment.checks.append(
                _check(
                    ReasonCode.GOODS_RECEIPT_REVERSED,
                    False,
                    "A receipt for this purchase-order line was reversed.",
                    line=line,
                    invoice_index=assignment.invoice_line_index,
                    invoice_quantity=quantity,
                )
            )
        if not line.active_receipts:
            assignment.checks.append(
                _check(
                    (
                        ReasonCode.RECEIPT_LINE_MISSING
                        if has_any_active_receipt
                        else ReasonCode.NO_GOODS_RECEIPT
                    ),
                    False,
                    "No active goods receipt covers this purchase-order line.",
                    line=line,
                    invoice_index=assignment.invoice_line_index,
                    invoice_quantity=quantity,
                )
            )
        if invoice_date is not None:
            after = [
                item
                for item in line.active_receipts
                if item.received_at.date() > _as_date(invoice_date)
            ]
            if after:
                assignment.checks.append(
                    _check(
                        ReasonCode.RECEIPT_AFTER_INVOICE,
                        False,
                        "Goods were received after the invoice date.",
                        line=line,
                        invoice_index=assignment.invoice_line_index,
                        invoice_quantity=quantity,
                    )
                )
        received = Decimal(line.effective_received_quantity)
        ordered = Decimal(line.ordered_quantity)
        if received > ordered + policy.quantity_absolute_tolerance:
            assignment.checks.append(
                _check(
                    ReasonCode.RECEIVED_QUANTITY_EXCEEDS_ORDERED,
                    False,
                    "Effective received quantity exceeds ordered quantity.",
                    line=line,
                    invoice_index=assignment.invoice_line_index,
                    expected=ordered,
                    actual=received,
                    tolerance=policy.quantity_absolute_tolerance,
                    invoice_quantity=quantity,
                )
            )
        if quantity is not None:
            available = Decimal(line.available_quantity)
            if (
                not policy.allow_partial_invoice
                and quantity < ordered - policy.quantity_absolute_tolerance
            ):
                assignment.checks.append(
                    _check(
                        ReasonCode.QUANTITY_MISMATCH,
                        False,
                        "Partial invoicing is disabled by the three-way policy.",
                        line=line,
                        invoice_index=assignment.invoice_line_index,
                        expected=ordered,
                        actual=quantity,
                        tolerance=policy.quantity_absolute_tolerance,
                        invoice_quantity=quantity,
                        evidence=list(invoice_line.quantity.evidence),
                    )
                )
            code = (
                ReasonCode.CUMULATIVE_QUANTITY_EXCEEDS_RECEIVED
                if Decimal(line.previously_allocated_quantity) > 0
                else ReasonCode.INVOICE_QUANTITY_EXCEEDS_RECEIVED
            )
            quantity_ok = quantity <= available + policy.quantity_absolute_tolerance
            assignment.checks.append(
                _check(
                    code,
                    quantity_ok,
                    "Invoice quantity is within available received quantity."
                    if quantity_ok
                    else "Invoice quantity exceeds available received quantity.",
                    line=line,
                    invoice_index=assignment.invoice_line_index,
                    expected=available,
                    actual=quantity,
                    tolerance=policy.quantity_absolute_tolerance,
                    invoice_quantity=quantity,
                    evidence=list(invoice_line.quantity.evidence),
                )
            )
            unit_price = invoice_line.unit_price.value
            if unit_price is not None:
                allowed = abs(po_line.unit_price) * policy.unit_price_relative_tolerance
                price_ok = abs(unit_price - po_line.unit_price) <= allowed
                assignment.checks.append(
                    _check(
                        ReasonCode.THREE_WAY_UNIT_PRICE_MISMATCH,
                        price_ok,
                        "Invoice unit price is within policy tolerance."
                        if price_ok
                        else "Invoice unit price differs from the purchase-order price.",
                        line=line,
                        invoice_index=assignment.invoice_line_index,
                        expected=po_line.unit_price,
                        actual=unit_price,
                        tolerance=allowed,
                        invoice_quantity=quantity,
                        evidence=list(invoice_line.unit_price.evidence),
                    )
                )
            line_total = invoice_line.line_total.value
            if line_total is not None:
                expected_total = quantity * po_line.unit_price
                total_ok = abs(line_total - expected_total) <= policy.amount_absolute_tolerance
                assignment.checks.append(
                    _check(
                        ReasonCode.THREE_WAY_LINE_AMOUNT_MISMATCH,
                        total_ok,
                        "Invoice line amount equals received quantity at the PO price."
                        if total_ok
                        else "Invoice line amount differs from quantity at the PO price.",
                        line=line,
                        invoice_index=assignment.invoice_line_index,
                        expected=expected_total,
                        actual=line_total,
                        tolerance=policy.amount_absolute_tolerance,
                        invoice_quantity=quantity,
                        evidence=list(invoice_line.line_total.evidence),
                    )
                )
            allocations.append(
                AllocationDraft(assignment.po_line_id, assignment.invoice_line_index, quantity)
            )
    all_checks = checks + [check for item in base.line_assignments for check in item.checks]
    failed = [check for check in all_checks if check.status == CheckStatus.FAILED]
    result = MatchResult(
        decision=MatchDecision.NEEDS_REVIEW if failed else MatchDecision.MATCHED,
        summary=MatchSummary(
            invoice_line_count=len(invoice.line_items),
            po_line_count=len(purchase_order.lines),
            assigned_line_count=len(base.line_assignments),
            passed_check_count=sum(c.status == CheckStatus.PASSED for c in all_checks),
            failed_check_count=len(failed),
        ),
        checks=checks,
        line_assignments=base.line_assignments,
        reason_codes=list(dict.fromkeys(check.code for check in failed)),
    )
    return result, allocations if result.decision == MatchDecision.MATCHED else []


def _as_date(value: date) -> date:
    return value
