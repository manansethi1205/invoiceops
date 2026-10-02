from decimal import Decimal

import pytest

from invoiceops.evaluation.supporting_hybrid import run_supporting_replay_evaluation


def test_frozen_supporting_replay_reports_both_roles_and_never_writes_canonical_records() -> None:
    first = run_supporting_replay_evaluation()
    second = run_supporting_replay_evaluation()
    assert first.example_count == 6
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert set(first.deterministic) == {
        "PURCHASE_ORDER", "GOODS_RECEIPT", "DELIVERY_NOTE"
    }
    assert first.deterministic["PURCHASE_ORDER"].header_exact["po_number"] == 2 / 3
    assert first.hybrid_replay["PURCHASE_ORDER"].header_exact["po_number"] == 2 / 3
    assert first.hybrid_replay["GOODS_RECEIPT"].header_exact["receipt_number"] == 1
    assert first.routed_document_rate == 3 / 6
    assert first.conflict_rate > 0
    assert first.abstention_rate > 0
    assert first.confirmation_rate is None
    assert first.false_canonical_record_count == 0
    assert first.estimated_model_cost_per_document is None
    assert "ABC-200" not in first.model_dump_json()
    assert "Widgets" not in first.model_dump_json()


def test_cost_requires_explicit_rates_and_is_a_synthetic_estimate() -> None:
    priced = run_supporting_replay_evaluation(
        input_cost_per_million=Decimal("1"),
        output_cost_per_million=Decimal("2"),
    )
    assert priced.estimated_model_cost_per_document is not None
    assert priced.estimated_model_cost_per_document > 0
    assert priced.usage_source.startswith("synthetic replay")
    with pytest.raises(ValueError, match="both token prices"):
        run_supporting_replay_evaluation(input_cost_per_million=Decimal("1"))
    with pytest.raises(ValueError, match="nonnegative"):
        run_supporting_replay_evaluation(
            input_cost_per_million=Decimal("-1"),
            output_cost_per_million=Decimal("2"),
        )
