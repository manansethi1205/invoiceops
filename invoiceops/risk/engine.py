from decimal import Decimal

from rapidfuzz.fuzz import ratio

from invoiceops.schemas.risk import (
    DuplicateRiskPolicy,
    RiskAssessmentResult,
    RiskDisposition,
    RiskFeatureSnapshot,
    RiskSeverity,
    RiskSignalCode,
    RiskSignalDraft,
)

SIGNAL_ORDER = {
    RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE: 0,
    RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER: 1,
    RiskSignalCode.SAME_PO_INVOICE_REPLAY: 2,
    RiskSignalCode.NEAR_DUPLICATE: 3,
    RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE: 4,
}


def assess_duplicate_risk(
    current: RiskFeatureSnapshot,
    historical: list[RiskFeatureSnapshot],
    policy: DuplicateRiskPolicy,
) -> RiskAssessmentResult:
    signals: list[RiskSignalDraft] = []
    if not current.complete:
        signals.append(
            RiskSignalDraft(
                code=RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE,
                severity=RiskSeverity.WARNING,
                observed={"missing_fields": list(current.missing_fields)},
                reference={"required_fields": _required_fields()},
                explanation=(
                    "Duplicate comparison is incomplete because required business-key "
                    f"features are unavailable: {', '.join(current.missing_fields)}."
                ),
            )
        )
    else:
        for reference in historical:
            if not reference.complete or reference.match_run_id == current.match_run_id:
                continue
            if reference.document_id == current.document_id:
                continue
            signals.extend(_compare(current, reference, policy))

    ordered = tuple(
        sorted(
            _deduplicate(signals),
            key=lambda signal: (
                SIGNAL_ORDER[signal.code],
                str(signal.comparison_match_run_id or ""),
            ),
        )
    )
    duplicate_found = any(
        signal.code != RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE for signal in ordered
    )
    incomplete = any(
        signal.code == RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE for signal in ordered
    )
    if duplicate_found or (incomplete and policy.route_incomplete_to_review):
        disposition = RiskDisposition.NEEDS_REVIEW
    elif incomplete:
        disposition = RiskDisposition.NOT_ASSESSABLE
    else:
        disposition = RiskDisposition.CLEAR
    return RiskAssessmentResult(disposition=disposition, features=current, signals=ordered)


def _compare(
    current: RiskFeatureSnapshot,
    reference: RiskFeatureSnapshot,
    policy: DuplicateRiskPolicy,
) -> list[RiskSignalDraft]:
    assert current.normalized_vendor is not None
    assert current.normalized_invoice_number is not None
    assert current.invoice_date is not None
    assert current.currency is not None
    assert current.total is not None
    assert reference.normalized_vendor is not None
    assert reference.normalized_invoice_number is not None
    assert reference.invoice_date is not None
    assert reference.currency is not None
    assert reference.total is not None

    same_vendor = current.normalized_vendor == reference.normalized_vendor
    same_number = current.normalized_invoice_number == reference.normalized_invoice_number
    same_date = current.invoice_date == reference.invoice_date
    same_currency = current.currency == reference.currency
    amount_difference = abs(Decimal(current.total) - Decimal(reference.total))
    amount_close = amount_difference <= policy.amount_absolute_tolerance
    same_po = current.purchase_order_id == reference.purchase_order_id
    exact = same_vendor and same_number and same_date and same_currency and amount_close
    observed = _comparison_values(current, amount_difference)
    expected = _comparison_values(reference, Decimal("0"))
    signals: list[RiskSignalDraft] = []

    if exact:
        signals.append(
            _signal(
                RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE,
                RiskSeverity.CRITICAL,
                reference,
                observed,
                expected,
                "Vendor, invoice number, date and currency match a prior invoice and the "
                "total is within the configured absolute tolerance.",
            )
        )
    elif same_vendor and same_number:
        signals.append(
            _signal(
                RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER,
                RiskSeverity.WARNING,
                reference,
                observed,
                expected,
                "The vendor and invoice number match a prior invoice, but another material "
                "business-key value differs.",
            )
        )

    if same_po and same_number:
        signals.append(
            _signal(
                RiskSignalCode.SAME_PO_INVOICE_REPLAY,
                RiskSeverity.CRITICAL,
                reference,
                observed,
                expected,
                "The same invoice number was previously processed against this purchase order.",
            )
        )

    date_distance = abs((current.invoice_date - reference.invoice_date).days)
    similarity = Decimal(str(ratio(
        current.normalized_invoice_number,
        reference.normalized_invoice_number,
    ))) / Decimal("100")
    if (
        not exact
        and same_vendor
        and same_currency
        and amount_close
        and date_distance <= policy.date_window_days
        and similarity >= policy.invoice_number_similarity_threshold
    ):
        near_observed = dict(observed)
        near_observed.update(
            {
                "invoice_number_similarity": format(similarity, "f"),
                "date_distance_days": date_distance,
            }
        )
        near_reference = dict(expected)
        near_reference.update(
            {
                "minimum_similarity": format(
                    policy.invoice_number_similarity_threshold, "f"
                ),
                "maximum_date_distance_days": policy.date_window_days,
            }
        )
        signals.append(
            _signal(
                RiskSignalCode.NEAR_DUPLICATE,
                RiskSeverity.WARNING,
                reference,
                near_observed,
                near_reference,
                "A prior invoice from the same vendor has a sufficiently similar invoice "
                "number, close date and total, and the same currency.",
            )
        )
    return signals


def _signal(
    code: RiskSignalCode,
    severity: RiskSeverity,
    reference: RiskFeatureSnapshot,
    observed: dict[str, object],
    expected: dict[str, object],
    explanation: str,
) -> RiskSignalDraft:
    return RiskSignalDraft(
        code=code,
        severity=severity,
        comparison_match_run_id=reference.match_run_id,
        observed=observed,
        reference=expected,
        explanation=explanation,
    )


def _comparison_values(
    features: RiskFeatureSnapshot, amount_difference: Decimal
) -> dict[str, object]:
    return {
        "normalized_vendor": features.normalized_vendor,
        "normalized_invoice_number": features.normalized_invoice_number,
        "invoice_date": features.invoice_date.isoformat() if features.invoice_date else None,
        "currency": features.currency,
        "total": features.total,
        "purchase_order_id": str(features.purchase_order_id),
        "document_id": str(features.document_id),
        "amount_difference": format(amount_difference, "f"),
    }


def _required_fields() -> list[str]:
    return ["normalized_vendor", "normalized_invoice_number", "invoice_date", "currency", "total"]


def _deduplicate(signals: list[RiskSignalDraft]) -> list[RiskSignalDraft]:
    unique: dict[tuple[RiskSignalCode, object], RiskSignalDraft] = {}
    for signal in signals:
        unique[(signal.code, signal.comparison_match_run_id)] = signal
    return list(unique.values())
