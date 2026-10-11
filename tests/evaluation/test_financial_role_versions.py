import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.financial_role_versions import VersionReport, run_versions
from tests.evaluation.financial_role_fixtures import write_contract_corpus


def test_three_versions_share_native_source_and_protect_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n")

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    manifest = write_contract_corpus(tmp_path, include_scan=False)
    output = tmp_path / "evals/reports/real-input/versions"
    private = tmp_path / "work/real-invoice-private/traces"
    report = run_versions(
        manifest, output, private, repository=tmp_path, cohort="synthetic_contract"
    )
    assert report.documents == report.pages == 11
    assert report.metric_version == "financial-role-three-version-v1"
    for strategy in (report.baseline, report.guard_03, report.guard_04):
        assert strategy.independent_role_labels is not None
        assert strategy.independent_role_labels.counts.present == 10
        assert strategy.unchanged_non_total.numerator == 11
    latest = report.guard_04.independent_role_labels
    assert latest is not None
    assert latest.counts.wrong == latest.counts.source_supported_role_errors == 0
    assert report.guard_04.false_abstentions is not None
    assert report.guard_04.false_abstentions.numerator == 0
    assert report.guard_04.false_abstentions.denominator == 6
    content = (output / "report.json").read_text()
    for secret in (str(tmp_path), "contract-0", "100.00", "source-0", "document_id"):
        assert secret not in content
    with pytest.raises(FileExistsError):
        run_versions(manifest, output, private, repository=tmp_path, cohort="synthetic_contract")
    with pytest.raises(FileExistsError):
        run_versions(
            manifest,
            output.parent / "fresh",
            private,
            repository=tmp_path,
            cohort="synthetic_contract",
        )
    payload = json.loads(content)
    payload.pop("metric_version")
    assert VersionReport.model_validate(payload).metric_version is None
    payload["private_notes"] = "secret"
    with pytest.raises(ValidationError):
        VersionReport.model_validate(payload)


def test_runtime_and_cli_imports_cannot_load_evaluation_or_provider() -> None:
    for module in (
        "invoiceops.extraction.financial_role_guard",
        "scripts.run_financial_role_versions",
    ):
        code = f"""
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {{'openai','httpx','httpcore','requests'}}:
            raise AssertionError('External SDK forbidden')
        runtime = {module!r}.startswith('invoiceops.extraction')
        if runtime and fullname.startswith('invoiceops.evaluation'):
            raise AssertionError('Runtime annotation dependency forbidden')
sys.meta_path.insert(0, Guard())
import {module}
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
        subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)
