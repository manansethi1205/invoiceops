import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from rapidfuzz.fuzz import ratio

from invoiceops.risk.engine import assess_duplicate_risk
from invoiceops.risk.normalization import normalize_invoice_number, normalize_vendor
from invoiceops.schemas.risk import (
    DuplicateRiskPolicy,
    RiskDisposition,
    RiskFeatureSnapshot,
    RiskSignalCode,
)


def feature(
    suffix: str,
    *,
    vendor: str | None = "synthetic vendor ltd",
    invoice_number: str | None = "inv001",
    invoice_date: date | None = date(2026, 9, 1),
    currency: str | None = "INR",
    total: str | None = "100.00",
    po: uuid.UUID | None = None,
) -> RiskFeatureSnapshot:
    missing = tuple(
        name
        for name, value in (
            ("normalized_vendor", vendor),
            ("normalized_invoice_number", invoice_number),
            ("invoice_date", invoice_date),
            ("currency", currency),
            ("total", total),
        )
        if value is None
    )
    return RiskFeatureSnapshot(
        normalized_vendor=vendor,
        normalized_invoice_number=invoice_number,
        invoice_date=invoice_date,
        currency=currency,
        total=total,
        purchase_order_id=po or uuid.uuid5(uuid.NAMESPACE_URL, f"po:{suffix}"),
        document_id=uuid.uuid5(uuid.NAMESPACE_URL, f"document:{suffix}"),
        extraction_run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"extraction:{suffix}"),
        match_run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"match:{suffix}"),
        missing_fields=missing,
    )


def codes(result: object) -> list[RiskSignalCode]:
    return [signal.code for signal in result.signals]  # type: ignore[attr-defined]


def test_normalization_is_unicode_aware_and_preserves_identifiers() -> None:
    assert normalize_vendor("  ACME—Parts, Ltd.  ") == "acme parts ltd"
    assert normalize_vendor("ＡＣＭＥ  GST09") == "acme gst09"
    assert normalize_invoice_number(" INV / 00-012_A ") == "inv00012a"
    assert normalize_invoice_number("000-42") == "00042"


def test_policy_rejects_float_financial_tolerance_and_documents_similarity_scale() -> None:
    with pytest.raises(ValidationError, match="strings or integers"):
        DuplicateRiskPolicy(amount_absolute_tolerance=0.02)
    assert DuplicateRiskPolicy().invoice_number_similarity_threshold == Decimal("0.92")


def test_exact_duplicate_and_amount_tolerance_boundary() -> None:
    reference = feature("old")
    at_boundary = feature("new", total="100.02")
    result = assess_duplicate_risk(at_boundary, [reference], DuplicateRiskPolicy())
    assert result.disposition == RiskDisposition.NEEDS_REVIEW
    assert RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE in codes(result)

    outside = feature("outside", total="100.0201")
    outside_result = assess_duplicate_risk(outside, [reference], DuplicateRiskPolicy())
    assert RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE not in codes(outside_result)
    assert RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER in codes(outside_result)


def test_reused_vendor_invoice_number_with_changed_amount_is_suspicious() -> None:
    result = assess_duplicate_risk(
        feature("new", total="500.00"), [feature("old")], DuplicateRiskPolicy()
    )
    assert codes(result) == [RiskSignalCode.REUSED_VENDOR_INVOICE_NUMBER]


def test_same_po_invoice_replay_is_explicit() -> None:
    po_id = uuid.uuid4()
    result = assess_duplicate_risk(
        feature("new", po=po_id, total="999.00"),
        [feature("old", po=po_id)],
        DuplicateRiskPolicy(),
    )
    assert RiskSignalCode.SAME_PO_INVOICE_REPLAY in codes(result)


def test_near_duplicate_similarity_threshold_boundary() -> None:
    reference = feature("old", invoice_number="inv001")
    current = feature("new", invoice_number="inv002")
    similarity = Decimal(str(ratio("inv001", "inv002"))) / Decimal("100")
    at_boundary = DuplicateRiskPolicy(invoice_number_similarity_threshold=similarity)
    above_boundary = DuplicateRiskPolicy(
        invoice_number_similarity_threshold=similarity + Decimal("0.0001")
    )
    assert RiskSignalCode.NEAR_DUPLICATE in codes(
        assess_duplicate_risk(current, [reference], at_boundary)
    )
    assert RiskSignalCode.NEAR_DUPLICATE not in codes(
        assess_duplicate_risk(current, [reference], above_boundary)
    )


def test_near_duplicate_date_window_boundary() -> None:
    reference = feature("old")
    boundary = feature("boundary", invoice_number="inv002", invoice_date=date(2026, 9, 8))
    outside = feature("outside", invoice_number="inv002", invoice_date=date(2026, 9, 9))
    policy = DuplicateRiskPolicy(invoice_number_similarity_threshold=Decimal("0.80"))
    assert RiskSignalCode.NEAR_DUPLICATE in codes(
        assess_duplicate_risk(boundary, [reference], policy)
    )
    assert RiskSignalCode.NEAR_DUPLICATE not in codes(
        assess_duplicate_risk(outside, [reference], policy)
    )


@pytest.mark.parametrize("same_number", [True, False])
def test_cross_vendor_collisions_are_not_duplicates(same_number: bool) -> None:
    number = "inv001" if same_number else "inv002"
    result = assess_duplicate_risk(
        feature("new", vendor="different vendor", invoice_number=number),
        [feature("old")],
        DuplicateRiskPolicy(invoice_number_similarity_threshold=Decimal("0.80")),
    )
    assert result.disposition == RiskDisposition.CLEAR
    assert result.signals == ()


@pytest.mark.parametrize(
    "field_name,changes",
    [
        ("normalized_vendor", {"vendor": None}),
        ("normalized_invoice_number", {"invoice_number": None}),
        ("invoice_date", {"invoice_date": None}),
        ("currency", {"currency": None}),
        ("total", {"total": None}),
    ],
)
def test_missing_critical_features_are_explicit(
    field_name: str, changes: dict[str, object]
) -> None:
    current = feature("missing", **changes)  # type: ignore[arg-type]
    routed = assess_duplicate_risk(current, [], DuplicateRiskPolicy())
    assert routed.disposition == RiskDisposition.NEEDS_REVIEW
    assert codes(routed) == [RiskSignalCode.DUPLICATE_CHECK_INCOMPLETE]
    assert field_name in routed.signals[0].observed["missing_fields"]

    not_routed = assess_duplicate_risk(
        current, [], DuplicateRiskPolicy(route_incomplete_to_review=False)
    )
    assert not_routed.disposition == RiskDisposition.NOT_ASSESSABLE


def test_signal_order_is_stable_and_no_opaque_score_is_returned() -> None:
    po_id = uuid.uuid4()
    reference = feature("old", po=po_id)
    result = assess_duplicate_risk(feature("new", po=po_id), [reference], DuplicateRiskPolicy())
    assert codes(result) == [
        RiskSignalCode.EXACT_BUSINESS_KEY_DUPLICATE,
        RiskSignalCode.SAME_PO_INVOICE_REPLAY,
    ]
    serialized = result.model_dump(mode="json")
    assert "score" not in serialized
    assert "risk_score" not in serialized


def test_same_document_and_extraction_are_not_a_separate_business_event() -> None:
    current = feature("same")
    result = assess_duplicate_risk(current, [current], DuplicateRiskPolicy())
    assert result.disposition == RiskDisposition.CLEAR


def test_new_extraction_of_same_document_is_not_a_separate_business_event() -> None:
    reference = feature("same-document")
    current = reference.model_copy(
        update={
            "extraction_run_id": uuid.uuid4(),
            "match_run_id": uuid.uuid4(),
        }
    )
    result = assess_duplicate_risk(current, [reference], DuplicateRiskPolicy())
    assert result.disposition == RiskDisposition.CLEAR


def test_date_arithmetic_never_uses_epoch_or_float() -> None:
    reference = feature("old")
    current = feature(
        "new",
        invoice_number="inv002",
        invoice_date=reference.invoice_date + timedelta(days=7),  # type: ignore[operator]
    )
    result = assess_duplicate_risk(
        current,
        [reference],
        DuplicateRiskPolicy(invoice_number_similarity_threshold=Decimal("0.80")),
    )
    assert result.signals[0].observed["date_distance_days"] == 7
