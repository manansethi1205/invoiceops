from pathlib import Path

from invoiceops.risk.evaluation import (
    run_duplicate_risk_evaluation,
    synthetic_duplicate_risk_scenarios,
    write_duplicate_risk_report,
)


def test_synthetic_evaluation_meets_safety_invariants(tmp_path: Path) -> None:
    scenarios = synthetic_duplicate_risk_scenarios()
    assert len(scenarios) >= 25
    report = run_duplicate_risk_evaluation(scenarios)
    assert report.expected_disposition_accuracy == 1.0
    assert report.duplicate_signal_precision == 1.0
    assert report.duplicate_signal_recall == 1.0
    assert report.known_duplicate_false_clear_count == 0
    assert report.clean_invoice_false_review_count == 0
    assert report.incomplete_assessment_accuracy == 1.0
    assert report.duplicate_assessment_count == 0

    write_duplicate_risk_report(tmp_path, report)
    markdown = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Synthetic/de-identified" in markdown
    assert "not production fraud-detection claims" in markdown
    assert "authorizes payment" in markdown
