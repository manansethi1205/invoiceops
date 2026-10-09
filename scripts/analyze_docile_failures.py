# mypy: disable-error-code=import-untyped
"""Compare the frozen baseline with value localization, exporting aggregate counts only."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from invoiceops.evaluation.adapters.docile import (
    DocileDatasetAdapter,
    DocileEvaluationMode,
    document_text_from_docile_ocr,
)
from invoiceops.evaluation.docile_analysis import (
    field_counts,
    localization_counts,
    status_counts,
    supported_fields,
)
from invoiceops.evaluation.docile_metrics import supported_f1, task_metrics
from invoiceops.evaluation.docile_predictions import invoice_to_docile_predictions
from invoiceops.evaluation.docile_predictions import official_docile_fields as _official_fields
from invoiceops.evaluation.docile_report import reserve_docile_output as reserve_output
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.value_grounding import ValueGroundedInvoiceExtractor


def evaluate_comparison(
    dataset_path: Path, manifest: Path, mode: DocileEvaluationMode
) -> dict[str, Any]:
    from docile.dataset import Dataset
    from docile.evaluation.evaluate import evaluate_dataset

    adapter = DocileDatasetAdapter()
    examples = adapter.load_examples(dataset_path, manifest, mode)
    documents: list[Any] = [example.document for example in examples]
    dataset = Dataset.from_documents("invoiceops-failure-analysis", documents)
    extractors = [DeterministicInvoiceExtractor(), ValueGroundedInvoiceExtractor()]
    invoices: dict[str, list[Any]] = {extractor.name: [] for extractor in extractors}
    predictions: dict[str, dict[str, dict[str, list[Any]]]] = {
        extractor.name: {"kile": {}, "lir": {}} for extractor in extractors
    }
    changed: Counter[str] = Counter()
    for index, example in enumerate(examples):
        if mode == DocileEvaluationMode.PRECOMPUTED_OCR:
            text = document_text_from_docile_ocr(example.document)
        else:
            pdf = example.document.data_paths.pdf_path(example.document_id).read_bytes()
            text = adapter.text_extractor.extract(pdf, "application/pdf")
        for extractor in extractors:
            invoice = extractor.extract(text)
            invoices[extractor.name].append(invoice)
            kile, lir = invoice_to_docile_predictions(invoice)
            predictions[extractor.name]["kile"][example.document_id] = kile
            predictions[extractor.name]["lir"][example.document_id] = lir
        before, after = (invoices[extractor.name][-1] for extractor in extractors)
        for field in ("invoice_number", "invoice_date", "subtotal", "tax", "total"):
            original, localized = getattr(before, field), getattr(after, field)
            if original.value != localized.value or original.status != localized.status:
                raise AssertionError("localization must preserve values and statuses")
            if original.evidence != localized.evidence:
                changed[field] += 1
        if before.line_items != after.line_items:
            raise AssertionError("localization must preserve line items")
        if (index + 1) % 25 == 0:
            print(f"{mode.value}: extracted {index + 1}/{len(examples)}", flush=True)
    variants = {}
    for extractor in extractors:
        prediction = predictions[extractor.name]
        result = evaluate_dataset(
            dataset, _official_fields(prediction["kile"]), _official_fields(prediction["lir"])
        )
        variants[extractor.name] = {
            "version": extractor.version,
            "header_status_counts": status_counts(invoices[extractor.name]),
            "tasks": {
                task: {
                    "supported_f1": supported_f1(result, task, supported_fields(task)),
                    "official_full": task_metrics(result, task),
                    "fields": field_counts(result, documents, task, supported_fields(task)),
                    "localization_diagnostics": localization_counts(
                        result, task, supported_fields(task)
                    ),
                }
                for task in ("kile", "lir")
            },
        }
    return {
        "mode": mode.value,
        "evaluated_documents": len(examples),
        "document_types": dict(
            Counter(str(document.annotation.document_type) for document in documents)
        ),
        "changed_header_evidence": dict(changed),
        "variants": variants,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DocILE aggregate failure analysis and targeted fix",
        "",
        f"Validation split loaded: {report['validation_documents']} documents.",
        "Both variants use the same fixed manifest and the same text/OCR per document.",
        "This is a development comparison on an external benchmark; "
        "it is not a held-out production claim.",
        "The candidate changes only header evidence locations; "
        "values, statuses and line items are preserved.",
        "Official metrics use the installed DocILE evaluator. "
        "Geometric overlap counts are diagnostic only.",
        "Raw documents, OCR, source text, predictions, matchings "
        "and document IDs are not exported.",
        "",
        "| Mode | Variant | Documents | Supported KILE F1 | Supported LIR F1 |",
        "|---|---|---:|---:|---:|",
    ]
    for mode in report["modes"]:
        for name, variant in mode["variants"].items():
            lines.append(
                f"| {mode['mode']} | {name}@{variant['version']} | "
                f"{mode['evaluated_documents']} | {variant['tasks']['kile']['supported_f1']:.4%} | "
                f"{variant['tasks']['lir']['supported_f1']:.4%} |"
            )
    lines += [
        "",
        "## Per-field counts",
        "",
        "| Mode | Variant | Field | TP | FP | FN | F1 |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for mode in report["modes"]:
        for name, variant in mode["variants"].items():
            for task in ("kile", "lir"):
                for field, metrics in variant["tasks"][task]["fields"].items():
                    lines.append(
                        f"| {mode['mode']} | {name} | {field} | {metrics['TP']} | "
                        f"{metrics['FP']} | {metrics['FN']} | {metrics['f1']:.4%} |"
                    )
    lines += [
        "",
        "Detailed status, overlap, document-type and changed-evidence counts are in report.json.",
        "Localization does not repair missing/ambiguous values or incorrect semantic mappings.",
        "The default production extractor and frozen 100-document reports remain unchanged.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    from docile.dataset import CachingConfig, Dataset

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=[mode.value for mode in DocileEvaluationMode])
    args = parser.parse_args()
    modes = [DocileEvaluationMode(args.mode)] if args.mode else list(DocileEvaluationMode)
    if DocileEvaluationMode.END_TO_END in modes:
        require_ocr_runtime(inspect_ocr_runtime())
    validation = Dataset(
        "val",
        args.dataset_path,
        load_annotations=False,
        load_ocr=False,
        cache_images=CachingConfig.OFF,
    )
    reserve_output(args.output_dir)
    report = {
        "dataset": "DocILE",
        "source_split": "val",
        "validation_documents": len(validation),
        "sample_manifest_sha256": hashlib.sha256(args.sample_manifest.read_bytes()).hexdigest(),
        "modes": [
            evaluate_comparison(args.dataset_path, args.sample_manifest, mode) for mode in modes
        ],
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    print("Wrote aggregate-only comparison to a new directory.", flush=True)


if __name__ == "__main__":
    main()
