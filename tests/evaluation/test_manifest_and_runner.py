import json
from pathlib import Path

import pytest

from invoiceops.evaluation.adapters.manifest import ManifestAdapter, ManifestDataset
from invoiceops.evaluation.runner import EvaluationRunner, HoldoutAccessError
from tests.synthetic_documents import generated_invoice_pdf


def _write_dataset(root: Path, *, split: str = "development") -> Path:
    manifest_dir = root / "manifests"
    document_dir = root / "documents"
    truth_dir = root / "ground_truth"
    manifest_dir.mkdir()
    document_dir.mkdir()
    truth_dir.mkdir()
    (document_dir / "invoice.pdf").write_bytes(generated_invoice_pdf("SYN-12345"))
    (truth_dir / "invoice.json").write_text(
        json.dumps(
            {
                "invoice_number": "SYN-12345",
                "invoice_date": "2026-09-19",
                "currency": "INR",
                "subtotal": "1200",
                "tax": "216",
                "total": "1416",
                "line_items": [
                    {
                        "description": "Industrial Filter",
                        "quantity": "2",
                        "unit_price": "500",
                        "line_total": "1000",
                    },
                    {
                        "description": "Mounting Bracket",
                        "quantity": "4",
                        "unit_price": "50",
                        "line_total": "200",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest = manifest_dir / "dataset.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "document_id": "synthetic-one",
                "split": split,
                "document_path": "../documents/invoice.pdf",
                "content_type": "application/pdf",
                "ground_truth_path": "../ground_truth/invoice.json",
                "tags": {"layout": "standard", "source": "digital"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest


def test_manifest_paths_resolve_relative_to_manifest(tmp_path: Path) -> None:
    dataset = ManifestAdapter().load(_write_dataset(tmp_path))
    assert dataset.read_document(dataset.examples[0]).startswith(b"%PDF")


def test_holdout_guard_runs_before_document_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _write_dataset(tmp_path, split="holdout")

    def forbidden_read(self: ManifestDataset, example: object) -> bytes:
        raise AssertionError("holdout document was accessed")

    monkeypatch.setattr(ManifestDataset, "read_document", forbidden_read)
    with pytest.raises(HoldoutAccessError, match="Re-run with --allow-holdout"):
        EvaluationRunner().run(manifest)


def test_runner_executes_extractors_directly_and_fingerprints_inputs(tmp_path: Path) -> None:
    manifest = _write_dataset(tmp_path)
    report, results = EvaluationRunner().run(manifest)

    assert report["metadata"]["extractor_version"] == "0.2.0"
    assert len(report["metadata"]["dataset_fingerprint"]) == 64
    assert results[0].prediction.schema_valid is True
    assert results[0].prediction.invoice is not None
    assert results[0].prediction.invoice.invoice_number.value == "SYN-12345"
