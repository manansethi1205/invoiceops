from invoiceops.matching.three_way_evaluation import run_evaluation


def test_three_way_evaluation_safety_invariants() -> None:
    report = run_evaluation()
    assert report.scenario_count >= 25
    assert report.expected_decision_accuracy == 1
    assert report.expected_reason_recall == 1
    assert report.false_auto_match_count == 0
    assert report.allocation_on_review_count == 0
    assert report.allocation_correctness_rate == 1
    assert report.cumulative_overbilling_detection_rate == 1
    assert report.idempotency_accuracy == 1
    assert report.serialized_overbilling_scenario_accuracy == 1
