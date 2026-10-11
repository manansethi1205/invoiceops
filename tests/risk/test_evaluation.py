import subprocess
from pathlib import Path

import pytest

from invoiceops.risk.evaluation import (
    run_duplicate_risk_evaluation,
    source_tree_fingerprint,
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


@pytest.mark.parametrize("git_available", [True, False])
def test_source_fingerprint_excludes_runtime_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, git_available: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("invoiceops/source.py")
    source.parent.mkdir()
    source.write_text("stable source", encoding="utf-8")
    artifacts = [
        ".tmp/pytest/test-case/temporary.txt",
        ".tmp/tmpacdc5frx/temporary.txt",
        "invoiceops/.tmp/pytest/temporary.txt",
        "invoiceops/__pycache__/source.pyc",
        "invoiceops/.pytest_cache/state",
        "invoiceops/.mypy_cache/state",
        "invoiceops/.ruff_cache/state",
        "invoiceops/.venv/source.py",
        "invoiceops/work/output.json",
        "invoiceops/tmp/temporary.txt",
        "evals/reports/generated/report.json",
        "outputs/report.json",
        "web/node_modules/dependency.js",
        "web/.next/build.js",
        ".uv-cache/state",
        "htmlcov/index.html",
        ".coverage",
        "web/tsconfig.tsbuildinfo",
    ]
    for name in artifacts:
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("runtime output", encoding="utf-8")

    def discover(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if not git_available:
            raise subprocess.CalledProcessError(1, "git")
        # Include directories and accidentally tracked caches, regardless of .gitignore.
        names = [*artifacts, ".tmp/tmpacdc5frx", source.as_posix(), source.as_posix()]
        return subprocess.CompletedProcess("git", 0, "\0".join(reversed(names)) + "\0")

    monkeypatch.setattr("invoiceops.risk.evaluation.subprocess.run", discover)
    read_bytes = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        assert path == source, "fingerprint attempted to read a runtime artifact"
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    fingerprint = source_tree_fingerprint()
    for name in artifacts:
        Path(name).write_text("changed runtime output", encoding="utf-8")
    assert source_tree_fingerprint() == fingerprint
    source.write_text("changed source", encoding="utf-8")
    assert source_tree_fingerprint() != fingerprint


def test_source_fingerprint_propagates_source_read_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source = Path("source.py")
    source.write_text("source", encoding="utf-8")
    monkeypatch.setattr(
        "invoiceops.risk.evaluation.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess("git", 0, "source.py\0"),
    )

    def denied_read(path: Path) -> bytes:
        raise PermissionError("selected source is unreadable")

    monkeypatch.setattr(Path, "read_bytes", denied_read)
    with pytest.raises(PermissionError, match="selected source is unreadable"):
        source_tree_fingerprint()
