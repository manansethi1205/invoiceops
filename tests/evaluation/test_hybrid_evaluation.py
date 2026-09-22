from decimal import Decimal

from invoiceops.evaluation.hybrid import run_hybrid_replay_evaluation


def test_hybrid_replay_is_safe_reproducible_and_cost_requires_explicit_pricing() -> None:
    first = run_hybrid_replay_evaluation()
    second = run_hybrid_replay_evaluation()
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.extractor_version == "0.3.0"
    assert first.prompt_version == "invoice-vision-v1"
    assert first.hybrid_replay.schema_valid_rate == 1
    assert first.safety["no_ungrounded_candidate_promoted"] is True
    assert first.safety["all_grounded_disagreements_abstained"] is True
    assert first.estimated_cost is None
    priced = run_hybrid_replay_evaluation(
        input_price_per_million=Decimal("1"), output_price_per_million=Decimal("2")
    )
    assert priced.estimated_cost is not None and priced.estimated_cost > 0
