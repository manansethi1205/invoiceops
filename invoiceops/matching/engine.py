from dataclasses import dataclass
from decimal import Decimal

from invoiceops.matching.normalization import description_similarity, normalize_description
from invoiceops.matching.validation import decimal_string, validate_invoice_financials
from invoiceops.schemas.extraction import EvidenceSpan, ExtractionStatus, Invoice, InvoiceLine
from invoiceops.schemas.matching import (
    CheckSeverity,
    CheckStatus,
    LineAssignment,
    MatchDecision,
    MatchingPolicy,
    MatchResult,
    MatchSummary,
    PurchaseOrderLineRead,
    PurchaseOrderRead,
    ReasonCode,
    ValidationCheck,
)


@dataclass(frozen=True)
class _Pair:
    invoice_index: int
    po_index: int
    score: float
    exact: bool


def _po_line_sort_key(line: PurchaseOrderLineRead) -> tuple[int, int | str]:
    try:
        return (0, int(line.line_number))
    except ValueError:
        return (1, line.line_number.casefold())


def _line_evidence(line: InvoiceLine) -> list[EvidenceSpan]:
    return [
        span
        for field in (line.description, line.quantity, line.unit_price, line.line_total)
        for span in field.evidence
    ]


def _comparison_check(
    *,
    code: ReasonCode,
    passed: bool,
    expected: Decimal | str,
    actual: Decimal | str,
    tolerance: Decimal | str | None,
    message: str,
    invoice_index: int,
    po_line: PurchaseOrderLineRead,
    evidence: list[EvidenceSpan],
) -> ValidationCheck:
    def serialize(value: Decimal | str | None) -> str | None:
        return decimal_string(value) if isinstance(value, Decimal) else value

    return ValidationCheck(
        code=code,
        status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
        severity=CheckSeverity.INFO if passed else CheckSeverity.ERROR,
        expected=serialize(expected),
        actual=serialize(actual),
        tolerance=serialize(tolerance),
        message=message,
        invoice_line_index=invoice_index,
        po_line_id=po_line.id,
        evidence=evidence,
    )


def _issue_check(
    code: ReasonCode,
    message: str,
    *,
    invoice_index: int | None = None,
    po_line: PurchaseOrderLineRead | None = None,
    expected: str | None = None,
    actual: str | None = None,
    tolerance: str | None = None,
    evidence: list[EvidenceSpan] | None = None,
) -> ValidationCheck:
    return ValidationCheck(
        code=code,
        status=CheckStatus.FAILED,
        severity=CheckSeverity.ERROR,
        expected=expected,
        actual=actual,
        tolerance=tolerance,
        message=message,
        invoice_line_index=invoice_index,
        po_line_id=None if po_line is None else po_line.id,
        evidence=evidence or [],
    )


def _candidate_pairs(
    invoice: Invoice,
    po: PurchaseOrderRead,
    policy: MatchingPolicy,
    checks: list[ValidationCheck],
) -> list[_Pair]:
    available_po = set(range(len(po.lines)))
    unresolved_invoice = set(range(len(invoice.line_items)))
    selected: list[_Pair] = []

    for invoice_index, invoice_line in enumerate(invoice.line_items):
        description = invoice_line.description.value
        if (
            invoice_line.description.status != ExtractionStatus.EXTRACTED
            or description is None
            or not normalize_description(description)
        ):
            checks.append(
                _issue_check(
                    ReasonCode.INVOICE_LINE_UNMATCHED,
                    "Invoice line description is missing or ambiguous.",
                    invoice_index=invoice_index,
                    evidence=list(invoice_line.description.evidence),
                )
            )
            unresolved_invoice.discard(invoice_index)
            continue
        normalized = normalize_description(description)
        exact_candidates = [
            po_index
            for po_index in available_po
            if normalize_description(po.lines[po_index].description) == normalized
        ]
        if len(exact_candidates) == 1:
            po_index = exact_candidates[0]
            selected.append(_Pair(invoice_index, po_index, 1.0, True))
            unresolved_invoice.discard(invoice_index)
            available_po.remove(po_index)
        elif len(exact_candidates) > 1:
            checks.append(
                _issue_check(
                    ReasonCode.DESCRIPTION_AMBIGUOUS,
                    "Invoice description exactly matches multiple purchase-order lines.",
                    invoice_index=invoice_index,
                    actual=description,
                    tolerance=str(policy.ambiguity_margin),
                    evidence=list(invoice_line.description.evidence),
                )
            )
            unresolved_invoice.discard(invoice_index)

    edges: list[_Pair] = []
    for invoice_index in sorted(unresolved_invoice):
        description = invoice.line_items[invoice_index].description.value
        assert description is not None
        scored = sorted(
            (
                _Pair(
                    invoice_index,
                    po_index,
                    description_similarity(description, po.lines[po_index].description),
                    False,
                )
                for po_index in available_po
            ),
            key=lambda pair: (
                -pair.score,
                _po_line_sort_key(po.lines[pair.po_index]),
                pair.invoice_index,
            ),
        )
        if not scored:
            checks.append(
                _issue_check(
                    ReasonCode.EXTRA_INVOICE_LINE,
                    "Invoice contains a line with no remaining purchase-order line.",
                    invoice_index=invoice_index,
                    evidence=_line_evidence(invoice.line_items[invoice_index]),
                )
            )
            continue
        eligible = [
            pair
            for pair in scored
            if pair.score >= policy.description_similarity_threshold
        ]
        if not eligible:
            best = scored[0]
            checks.append(
                _issue_check(
                    ReasonCode.DESCRIPTION_BELOW_THRESHOLD,
                    "Best purchase-order description is below the matching threshold.",
                    invoice_index=invoice_index,
                    expected=str(policy.description_similarity_threshold),
                    actual=f"{best.score:.6f}",
                    evidence=list(invoice.line_items[invoice_index].description.evidence),
                )
            )
            continue
        best = eligible[0]
        if len(eligible) > 1 and best.score - eligible[1].score < policy.ambiguity_margin:
            checks.append(
                _issue_check(
                    ReasonCode.DESCRIPTION_AMBIGUOUS,
                    "The two best purchase-order descriptions are too close to distinguish.",
                    invoice_index=invoice_index,
                    expected=f"margin >= {policy.ambiguity_margin}",
                    actual=f"{best.score - eligible[1].score:.6f}",
                    evidence=list(invoice.line_items[invoice_index].description.evidence),
                )
            )
            continue
        edges.extend(eligible)

    assigned_invoices = {pair.invoice_index for pair in selected}
    assigned_po = {pair.po_index for pair in selected}
    for pair in sorted(
        edges,
        key=lambda item: (
            -item.score,
            _po_line_sort_key(po.lines[item.po_index]),
            item.invoice_index,
        ),
    ):
        if pair.invoice_index in assigned_invoices or pair.po_index in assigned_po:
            continue
        selected.append(pair)
        assigned_invoices.add(pair.invoice_index)
        assigned_po.add(pair.po_index)

    for invoice_index in sorted(unresolved_invoice - assigned_invoices):
        if any(check.invoice_line_index == invoice_index for check in checks):
            continue
        checks.append(
            _issue_check(
                ReasonCode.INVOICE_LINE_UNMATCHED,
                "Invoice line could not be assigned one-to-one to a purchase-order line.",
                invoice_index=invoice_index,
                evidence=_line_evidence(invoice.line_items[invoice_index]),
            )
        )
    for po_index, po_line in enumerate(po.lines):
        if po_index not in assigned_po:
            checks.append(
                _issue_check(
                    ReasonCode.PO_LINE_UNMATCHED,
                    "Purchase-order line has no matching invoice line.",
                    po_line=po_line,
                    expected=po_line.description,
                )
            )
    return sorted(selected, key=lambda pair: pair.invoice_index)


def _assignment(
    invoice: Invoice,
    po: PurchaseOrderRead,
    pair: _Pair,
    policy: MatchingPolicy,
) -> LineAssignment:
    invoice_line = invoice.line_items[pair.invoice_index]
    po_line = po.lines[pair.po_index]
    evidence = _line_evidence(invoice_line)
    checks = [
        _comparison_check(
            code=ReasonCode.DESCRIPTION_BELOW_THRESHOLD,
            passed=pair.score >= policy.description_similarity_threshold,
            expected=f">= {policy.description_similarity_threshold}",
            actual=f"{pair.score:.6f}",
            tolerance=None,
            message="Description similarity meets the matching threshold.",
            invoice_index=pair.invoice_index,
            po_line=po_line,
            evidence=list(invoice_line.description.evidence),
        )
    ]
    quantity = invoice_line.quantity.value
    if invoice_line.quantity.status == ExtractionStatus.EXTRACTED and quantity is not None:
        difference = abs(quantity - po_line.ordered_quantity)
        checks.append(
            _comparison_check(
                code=ReasonCode.QUANTITY_MISMATCH,
                passed=difference <= policy.quantity_absolute_tolerance,
                expected=po_line.ordered_quantity,
                actual=quantity,
                tolerance=policy.quantity_absolute_tolerance,
                message=(
                    "Invoice quantity is within tolerance."
                    if difference <= policy.quantity_absolute_tolerance
                    else "Invoice quantity differs from ordered quantity."
                ),
                invoice_index=pair.invoice_index,
                po_line=po_line,
                evidence=list(invoice_line.quantity.evidence),
            )
        )
    unit_price = invoice_line.unit_price.value
    if invoice_line.unit_price.status == ExtractionStatus.EXTRACTED and unit_price is not None:
        if po_line.unit_price == 0:
            price_passed = unit_price == 0
            price_tolerance = Decimal("0")
        else:
            price_tolerance = abs(po_line.unit_price) * policy.unit_price_relative_tolerance
            price_passed = abs(unit_price - po_line.unit_price) <= price_tolerance
        checks.append(
            _comparison_check(
                code=ReasonCode.UNIT_PRICE_MISMATCH,
                passed=price_passed,
                expected=po_line.unit_price,
                actual=unit_price,
                tolerance=price_tolerance,
                message=(
                    "Invoice unit price is within tolerance."
                    if price_passed
                    else "Invoice unit price differs from the purchase-order price."
                ),
                invoice_index=pair.invoice_index,
                po_line=po_line,
                evidence=list(invoice_line.unit_price.evidence),
            )
        )
    line_total = invoice_line.line_total.value
    if invoice_line.line_total.status == ExtractionStatus.EXTRACTED and line_total is not None:
        expected_total = po_line.ordered_quantity * po_line.unit_price
        amount_passed = abs(line_total - expected_total) <= policy.amount_absolute_tolerance
        checks.append(
            _comparison_check(
                code=ReasonCode.LINE_AMOUNT_MISMATCH,
                passed=amount_passed,
                expected=expected_total,
                actual=line_total,
                tolerance=policy.amount_absolute_tolerance,
                message=(
                    "Invoice line amount is within tolerance."
                    if amount_passed
                    else "Invoice line amount differs from the purchase-order line amount."
                ),
                invoice_index=pair.invoice_index,
                po_line=po_line,
                evidence=list(invoice_line.line_total.evidence),
            )
        )
    return LineAssignment(
        invoice_line_index=pair.invoice_index,
        po_line_id=po_line.id,
        po_line_number=po_line.line_number,
        description_score=pair.score,
        exact_description=pair.exact,
        checks=checks,
        evidence=evidence,
    )


def match_invoice(
    invoice: Invoice,
    purchase_order: PurchaseOrderRead,
    policy: MatchingPolicy | None = None,
) -> MatchResult:
    effective_policy = policy or MatchingPolicy()
    checks = validate_invoice_financials(invoice, effective_policy)
    currency = invoice.currency.value
    currency_matches = (
        invoice.currency.status == ExtractionStatus.EXTRACTED
        and currency == purchase_order.currency
    )
    checks.append(
        ValidationCheck(
            code=ReasonCode.CURRENCY_MISMATCH,
            status=CheckStatus.PASSED if currency_matches else CheckStatus.FAILED,
            severity=CheckSeverity.INFO if currency_matches else CheckSeverity.ERROR,
            expected=purchase_order.currency,
            actual=currency or "missing",
            tolerance=None,
            message=(
                "Invoice and purchase-order currencies match."
                if currency_matches
                else "Invoice currency differs from the purchase-order currency."
            ),
            evidence=list(invoice.currency.evidence),
        )
    )
    pairs = _candidate_pairs(invoice, purchase_order, effective_policy, checks)
    assignments = [
        _assignment(invoice, purchase_order, pair, effective_policy) for pair in pairs
    ]
    all_checks = checks + [check for assignment in assignments for check in assignment.checks]
    failed = [check for check in all_checks if check.status == CheckStatus.FAILED]
    reason_codes = list(dict.fromkeys(check.code for check in failed))
    decision = MatchDecision.NEEDS_REVIEW if failed else MatchDecision.MATCHED
    return MatchResult(
        decision=decision,
        summary=MatchSummary(
            invoice_line_count=len(invoice.line_items),
            po_line_count=len(purchase_order.lines),
            assigned_line_count=len(assignments),
            passed_check_count=sum(check.status == CheckStatus.PASSED for check in all_checks),
            failed_check_count=len(failed),
        ),
        checks=checks,
        line_assignments=assignments,
        reason_codes=reason_codes,
    )
