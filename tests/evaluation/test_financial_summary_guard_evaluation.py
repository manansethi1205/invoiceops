import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.financial_summary_guard import PairedReport, run_pair
from invoiceops.evaluation.real_input import run_private_benchmark
from tests.evaluation.test_real_input import annotation, dataset
from tests.synthetic_documents import generated_invoice_pdf


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def test_paired_accounting_fingerprint_privacy_and_overwrite(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network/provider calls forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    body = generated_invoice_pdf()
    manifest = dataset(repository, labels=[annotation(body)])
    baseline = run_private_benchmark(
        manifest, repository / "evals/reports/real-input/baseline", repository=repository
    )
    output = repository / "evals/reports/real-input/paired"
    private = repository / "work/real-invoice-private/diagnostics/paired"
    report = run_pair(manifest, output, private, repository=repository)
    assert report.corpus_fingerprint == baseline.corpus_fingerprint
    assert report.documents == report.pages == 1
    assert report.baseline.correct == report.candidate.correct == 1
    assert report.baseline.present == report.candidate.present == 1
    assert report.added_abstentions == 0
    assert report.unchanged_non_total_documents == report.unchanged_row_documents == 1
    content = (output / "report.json").read_text(encoding="utf-8")
    assert "SYN-12345" not in content and "private-id" not in content
    assert str(repository) not in content
    assert (private / "cases.jsonl").exists()
    before = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_pair(manifest, output, private, repository=repository)
    assert (output / "report.json").read_bytes() == before
    with pytest.raises(FileExistsError):
        run_pair(
            manifest, repository / "evals/reports/real-input/fresh", private, repository=repository
        )
    with pytest.raises(ValueError):
        run_pair(
            manifest,
            repository / "public",
            repository / "work/real-invoice-private/fresh",
            repository=repository,
        )
    data = json.loads(content)
    data["document_id"] = "private-id"
    with pytest.raises(ValidationError):
        PairedReport.model_validate(data)


def test_runtime_guard_has_no_evaluation_or_external_imports() -> None:
    code = """
import importlib.abc, socket, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden_sdk = fullname.split('.')[0] in {'openai','httpx','httpcore'}
        if fullname.startswith('invoiceops.evaluation') or forbidden_sdk:
            raise AssertionError('Runtime annotations or external SDK imports forbidden')
sys.meta_path.insert(0, Guard())
import invoiceops.extraction.financial_summary_guard
assert not any(k.startswith('invoiceops.evaluation') for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_paired_cli_import_graph_has_no_external_sdk() -> None:
    code = """
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai','httpx','httpcore'}:
            raise AssertionError('External SDK forbidden')
sys.meta_path.insert(0, Guard())
import scripts.run_financial_summary_guard_evaluation
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
