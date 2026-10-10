from decimal import Decimal
from pathlib import Path

import pytest

from invoiceops.evaluation.hybrid import run_hybrid_replay_evaluation, write_hybrid_report


def test_hybrid_replay_is_safe_reproducible_and_cost_requires_explicit_pricing() -> None:
    first = run_hybrid_replay_evaluation()
    second = run_hybrid_replay_evaluation()
    assert first.dataset_fingerprint == second.dataset_fingerprint
    assert first.extractor_version == "0.4.0"
    assert first.prompt_version == "invoice-vision-v1"
    assert first.hybrid_replay.schema_valid_rate == 1
    assert first.safety["no_ungrounded_candidate_promoted"] is True
    assert first.safety["all_grounded_disagreements_abstained"] is True
    assert first.estimated_cost is None
    priced = run_hybrid_replay_evaluation(
        input_price_per_million=Decimal("1"), output_price_per_million=Decimal("2")
    )
    assert priced.estimated_cost is not None and priced.estimated_cost > 0


def test_replay_report_is_versioned_and_cannot_overwrite(tmp_path: Path) -> None:
    report = run_hybrid_replay_evaluation()
    output = tmp_path / "fresh"
    write_hybrid_report(output, report)
    original = (output / "report.json").read_bytes()
    assert "Hybrid replay 0.4.0" in (output / "report.md").read_text()
    with pytest.raises(FileExistsError):
        write_hybrid_report(output, report)
    assert (output / "report.json").read_bytes() == original
