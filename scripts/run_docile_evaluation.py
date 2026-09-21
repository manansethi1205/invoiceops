# mypy: disable-error-code=import-untyped
import argparse
import hashlib
from pathlib import Path
from typing import Any

from invoiceops.evaluation.adapters.docile import (
    DocileDatasetAdapter,
    DocileEvaluationMode,
    load_sample_manifest,
)
from invoiceops.evaluation.docile_mapping import (
    DOCILE_KILE_TO_INVOICEOPS,
    DOCILE_LIR_TO_INVOICEOPS,
)
from invoiceops.evaluation.docile_metrics import supported_f1, task_metrics
from invoiceops.evaluation.docile_predictions import (
    DocilePrediction,
    invoice_to_docile_predictions,
    write_docile_predictions,
)
from invoiceops.evaluation.docile_report import (
    DocileAggregateReport,
    DocileModeMetrics,
    write_docile_aggregate_report,
)
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime
from invoiceops.extraction.version import EXTRACTOR_NAME, EXTRACTOR_VERSION


def _official_fields(predictions: dict[str, list[DocilePrediction]]) -> dict[str, list[Any]]:
    from docile.dataset import BBox, Field

    return {
        document_id: [
            Field(
                page=prediction.page,
                bbox=BBox(*prediction.bbox),
                fieldtype=prediction.fieldtype,
                text=prediction.text,
                line_item_id=prediction.line_item_id,
            )
            for prediction in fields
        ]
        for document_id, fields in predictions.items()
    }


def evaluate_mode(
    dataset_path: Path,
    manifest_path: Path,
    output_dir: Path,
    mode: DocileEvaluationMode,
) -> DocileModeMetrics:
    from docile.dataset import Dataset
    from docile.evaluation.evaluate import evaluate_dataset

    adapter = DocileDatasetAdapter()
    examples = adapter.load_examples(dataset_path, manifest_path, mode)
    kile: dict[str, list[DocilePrediction]] = {}
    lir: dict[str, list[DocilePrediction]] = {}
    for example in examples:
        invoice = adapter.extract(example)
        kile[example.document_id], lir[example.document_id] = invoice_to_docile_predictions(invoice)
    mode_dir = output_dir / mode.value.replace("_", "-")
    write_docile_predictions(mode_dir / "kile_predictions.json", kile)
    write_docile_predictions(mode_dir / "lir_predictions.json", lir)
    dataset = Dataset.from_documents("val-sample", [example.document for example in examples])
    result = evaluate_dataset(dataset, _official_fields(kile), _official_fields(lir))
    kile_full = task_metrics(result, "kile")
    lir_full = task_metrics(result, "lir")
    return DocileModeMetrics(
        mode=mode.value,
        document_count=len(examples),
        supported_subset_kile_f1=supported_f1(
            result, "kile", set(DOCILE_KILE_TO_INVOICEOPS)
        ),
        supported_subset_lir_f1=supported_f1(
            result, "lir", set(DOCILE_LIR_TO_INVOICEOPS)
        ),
        official_full_kile_f1=float(kile_full["f1"]),
        official_full_lir_f1=float(lir_full["f1"]),
        official_full_kile_ap=float(kile_full["AP"]),
        official_full_lir_ap=float(lir_full["AP"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run both DocILE evaluation modes")
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("evals/reports/docile/0.2.0")
    )
    arguments = parser.parse_args()
    require_ocr_runtime(inspect_ocr_runtime())
    manifest = load_sample_manifest(arguments.sample_manifest)
    modes = [
        evaluate_mode(
            arguments.dataset_path, arguments.sample_manifest, arguments.output_dir, mode
        )
        for mode in DocileEvaluationMode
    ]
    report = DocileAggregateReport(
        extractor_name=EXTRACTOR_NAME,
        extractor_version=EXTRACTOR_VERSION,
        sample_seed=manifest.seed,
        sample_manifest_sha256=hashlib.sha256(arguments.sample_manifest.read_bytes()).hexdigest(),
        modes=modes,
    )
    write_docile_aggregate_report(arguments.output_dir, report)
    print("wrote aggregate-only DocILE report; raw predictions remain ignored")


if __name__ == "__main__":
    main()
