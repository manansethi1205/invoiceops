import json
from pathlib import Path

from invoiceops.evaluation.reporting import write_outputs
from invoiceops.evaluation.runner import EvaluationRunner
from tests.evaluation.test_manifest_and_runner import _write_dataset


def test_outputs_exclude_paths_evidence_text_and_tracebacks(tmp_path: Path) -> None:
    report, results = EvaluationRunner().run(_write_dataset(tmp_path))
    output = tmp_path / "reports"
    write_outputs(output, report, results)

    assert {path.name for path in output.iterdir()} == {
        "report.json",
        "report.md",
        "predictions.jsonl",
        "failures.jsonl",
    }
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output.iterdir())
    assert str(tmp_path) not in combined
    assert "Traceback" not in combined
    assert '"evidence"' not in combined
    prediction = json.loads((output / "predictions.jsonl").read_text(encoding="utf-8"))
    assert prediction["document_id"] == "synthetic-one"
