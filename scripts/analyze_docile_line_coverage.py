# mypy: disable-error-code=import-untyped
"""Stage diagnostics and an offline, same-input invoice line parser comparison."""

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
from invoiceops.evaluation.docile_analysis import field_counts, supported_fields
from invoiceops.evaluation.docile_metrics import task_metrics
from invoiceops.evaluation.docile_predictions import (
    invoice_to_docile_predictions,
    official_docile_fields,
)
from invoiceops.evaluation.docile_report import reserve_docile_output
from invoiceops.evaluation.line_coverage import (
    annotated_stage_counts,
    micro_counts,
    trace_line_parser,
)
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.table_layout import detect_table_header
from invoiceops.schemas.extraction import DocumentText


def private_cache_root() -> Path:
    """Only permit raw text caching on a dedicated in-container tmpfs, never a host bind."""
    mount = Path("/private-cache")
    mounts = Path("/proc/mounts")
    if not mounts.exists() or not any(
        len(parts := line.split()) > 2 and parts[1] == str(mount) and parts[2] == "tmpfs"
        for line in mounts.read_text(encoding="utf-8").splitlines()
    ):
        raise RuntimeError("Private cache requires the dedicated /private-cache tmpfs")
    return mount


def evaluate_mode(args: Any, mode: DocileEvaluationMode) -> dict[str, Any]:
    from docile.dataset import Dataset
    from docile.evaluation.evaluate import evaluate_dataset

    adapter = DocileDatasetAdapter()
    examples: list[Any] = adapter.load_examples(args.dataset_path, args.sample_manifest, mode)
    if len(examples) != 500:
        raise ValueError("Use the fixed 500-document validation manifest")
    documents: list[Any] = [example.document for example in examples]
    dataset = Dataset.from_documents("invoiceops-line-coverage-development", documents)
    extractors: list[Any] = [DeterministicInvoiceExtractor()]
    detectors: dict[str, Any] = {extractors[0].name: detect_table_header}
    trace_options: dict[str, dict[str, Any]] = {extractors[0].name: {}}
    if not args.baseline_only:
        from invoiceops.extraction.line_coverage_candidate import (
            LineCoverageInvoiceExtractor,
            candidate_column_ranges,
            candidate_is_footer,
            candidate_row_is_probable,
            detect_candidate_header,
        )

        candidate = LineCoverageInvoiceExtractor()
        extractors.append(candidate)
        detectors[candidate.name] = detect_candidate_header
        trace_options[candidate.name] = {
            "range_builder": candidate_column_ranges,
            "row_validator": candidate_row_is_probable,
            "footer_detector": candidate_is_footer,
        }
    counts: dict[str, Counter[str]] = {e.name: Counter() for e in extractors}
    signatures: dict[str, Counter[str]] = {e.name: Counter() for e in extractors}
    probes: dict[str, Counter[str]] = {e.name: Counter() for e in extractors}
    predictions: dict[str, dict[str, dict[str, list[Any]]]] = {
        e.name: {"kile": {}, "lir": {}} for e in extractors
    }
    manifest_hash = hashlib.sha256(args.sample_manifest.read_bytes()).hexdigest()
    cache = private_cache_root() / mode.value if args.use_private_cache else None
    if cache is not None:
        cache.mkdir(exist_ok=True)
    for index, example in enumerate(examples):
        path = cache / f"{index:04d}.json" if cache else None
        if path and path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if cached["manifest_sha256"] != manifest_hash:
                raise ValueError("Private text cache manifest mismatch")
            text = DocumentText.model_validate(cached["text"])
        else:
            if mode == DocileEvaluationMode.PRECOMPUTED_OCR:
                text = document_text_from_docile_ocr(example.document)
            else:
                pdf = example.document.data_paths.pdf_path(example.document_id).read_bytes()
                text = adapter.text_extractor.extract(pdf, "application/pdf")
            if path is not None:
                path.write_text(
                    json.dumps(
                        {"manifest_sha256": manifest_hash, "text": text.model_dump(mode="json")}
                    ),
                    encoding="utf-8",
                )
        before = None
        for extractor in extractors:
            invoice = extractor.extract(text)
            if before is not None:
                for field in (
                    "invoice_number",
                    "invoice_date",
                    "currency",
                    "subtotal",
                    "tax",
                    "total",
                ):
                    if getattr(before, field) != getattr(invoice, field):
                        raise AssertionError("Line parser must preserve headers")
            before = invoice
            trace = trace_line_parser(
                text,
                invoice.line_items,
                detectors[extractor.name],
                **trace_options[extractor.name],
            )
            counts[extractor.name].update(trace.counts)
            counts[extractor.name].update(
                annotated_stage_counts(trace, example.document.annotation.li_fields)
            )
            signatures[extractor.name].update(trace.rejected_header_signatures)
            probes[extractor.name].update(trace.probes)
            kile, lir = invoice_to_docile_predictions(invoice)
            predictions[extractor.name]["kile"][example.document_id] = kile
            predictions[extractor.name]["lir"][example.document_id] = lir
        if (index + 1) % 50 == 0:
            print(f"{mode.value}: {index + 1}/{len(examples)}", flush=True)
    variants = {}
    for extractor in extractors:
        prediction = predictions[extractor.name]
        result = evaluate_dataset(
            dataset,
            official_docile_fields(prediction["kile"]),
            official_docile_fields(prediction["lir"]),
        )
        fields = field_counts(result, documents, "lir", supported_fields("lir"))
        variants[extractor.name] = {
            "version": extractor.version,
            "stage_counts": dict(counts[extractor.name]),
            "rejected_header_signatures": dict(signatures[extractor.name]),
            "bounded_header_probes": dict(probes[extractor.name]),
            "supported_lir_fields": fields,
            "supported_lir_micro": micro_counts(fields),
            "official_full_lir": task_metrics(result, "lir"),
        }
    return {"mode": mode.value, "evaluated_documents": len(examples), "variants": variants}


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Invoice line-item coverage: observed DocILE development split",
        "",
        "All 500 validation documents are observed development data, not a fresh holdout.",
        "Baseline and candidate consume identical source text when both are present.",
        "Only aggregate counters and official location-based LIR metrics are exported.",
        "No raw documents, source text, IDs, predictions or matchings are exported.",
        "Stage attribution uses token-center containment; it is diagnostic, not official scoring.",
        "",
        "| Mode | Variant | Field | TP | FP | FN | Pred | GT | Precision | Recall | F1 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in report["modes"]:
        for name, variant in mode["variants"].items():
            for field, metric in list(variant["supported_lir_fields"].items()) + [
                ("supported micro", variant["supported_lir_micro"])
            ]:
                tp, fp, fn = (int(metric[k]) for k in ("TP", "FP", "FN"))
                lines.append(
                    f"| {mode['mode']} | {name}@{variant['version']} | {field} | {tp} | {fp} | "
                    f"{fn} | {tp + fp} | {tp + fn} | {metric['precision']:.4%} | "
                    f"{metric['recall']:.4%} | {metric['f1']:.4%} |"
                )
    lines += [
        "",
        "## Stage counters",
        "",
        "| Mode | Variant | Counter | Count |",
        "|---|---|---|---:|",
    ]
    for mode in report["modes"]:
        for name, variant in mode["variants"].items():
            for key, count in sorted(variant["stage_counts"].items()):
                lines.append(f"| {mode['mode']} | {name} | {key} | {count} |")
    lines += [
        "",
        "Header signatures and bounded alias probes are in report.json.",
        "Multiple visual rows can reflect legitimate wrapping; they are not automatically errors.",
        "Financial values are observed, never inferred. No production strategy is changed.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", type=Path, required=True)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--mode", choices=[mode.value for mode in DocileEvaluationMode])
    parser.add_argument("--use-private-cache", action="store_true")
    args = parser.parse_args()
    modes = [DocileEvaluationMode(args.mode)] if args.mode else list(DocileEvaluationMode)
    if DocileEvaluationMode.END_TO_END in modes:
        require_ocr_runtime(inspect_ocr_runtime())
    if args.use_private_cache:
        private_cache_root()
    reserve_docile_output(args.output_dir)
    report: dict[str, Any] = {
        "dataset": "DocILE",
        "source_split": "val",
        "scope": "entire observed development validation split",
        "sample_manifest_sha256": hashlib.sha256(args.sample_manifest.read_bytes()).hexdigest(),
        "modes": [evaluate_mode(args, mode) for mode in modes],
    }
    if any(mode["evaluated_documents"] != 500 for mode in report["modes"]):
        raise ValueError("This analysis requires the fixed 500-document validation manifest")
    for name, content in (
        ("report.json", json.dumps(report, indent=2, sort_keys=True) + "\n"),
        ("report.md", render_report(report)),
    ):
        with (args.output_dir / name).open("x", encoding="utf-8") as output:
            output.write(content)
    print("Wrote aggregate-only line coverage report.", flush=True)


if __name__ == "__main__":
    main()
