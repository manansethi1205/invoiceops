from invoiceops.matching.evaluation import (
    render_matching_report,
    run_matching_evaluation,
    synthetic_matching_scenarios,
)


def test_business_evaluation_is_safe_and_aggregate_only() -> None:
    scenarios = synthetic_matching_scenarios()
    report = run_matching_evaluation(scenarios)
    markdown = render_matching_report(report)

    assert len(scenarios) == report.scenario_count == 18
    assert report.expected_decision_accuracy == 1
    assert report.false_auto_match_count == 0
    assert report.reason_code_accuracy == 1
    assert report.policy_version == "matching-v1"
    assert "Industrial Filter" not in markdown
    assert "C:\\" not in markdown
