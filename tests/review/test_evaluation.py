import json
from pathlib import Path

from invoiceops.review.evaluation import run_review_evaluation, write_review_report


def test_review_evaluation_is_safe_and_writes_aggregate_reports(tmp_path: Path) -> None:
    report = run_review_evaluation()
    assert report.scenario_count >= 15
    assert report.expected_transition_accuracy == 1
    assert report.allowed_transition_accuracy == 1
    assert report.invalid_transition_rejection_rate == 1
    assert report.stale_version_rejection_accuracy == 1
    assert report.unauthorized_owner_action_rejection_rate == 1
    assert report.idempotent_replay_rejection_accuracy == 1
    assert report.duplicate_case_count == 0
    assert report.event_chain_verification_rate == 1
    assert report.state_reconstruction_accuracy == 1
    assert report.false_auto_resolution_count == 0

    write_review_report(tmp_path, report)
    parsed = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert parsed["scenario_count"] == report.scenario_count
    assert "Synthetic scenario set" in (tmp_path / "report.md").read_text(encoding="utf-8")
