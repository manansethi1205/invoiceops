# mypy: disable-error-code=import-untyped
"""Offline private review preparation and aggregate-only export for header observations."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from invoiceops.evaluation.adapters.docile import (
    DocileDatasetAdapter,
    DocileEvaluationMode,
    document_text_from_docile_ocr,
    load_sample_manifest,
)
from invoiceops.evaluation.header_miss_audit import (
    MODES,
    REQUIRED_EVIDENCE,
    Observation,
    PairedGroup,
    aggregate_audit,
    aggregate_output,
    grouped_fields,
    observe_groups,
    pair_groups,
    private_output,
    review_template,
    select_groups,
    write_aggregate,
)
from invoiceops.evaluation.line_coverage import trace_line_parser
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime
from invoiceops.schemas.extraction import DocumentText


def _write_private(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")


def _private_rubric(root: Path) -> None:
    lines = [
        "# PRIVATE qualitative review rubric",
        "",
        "Keep all source material, review labels and notes private and out of routine logs.",
        "Observe source page, tokens, annotation boxes, visual rows and earlier pages privately.",
        "Use one primary explanation per mode only after inspecting the required evidence.",
        "A prior header or later page is a continuation signal, not confirmation.",
        "Detected controls also need visual verification; detection need not mean correctness.",
        "Keep competing explanations in private notes. Use other_or_uncertain when unresolved.",
        "Edit reviews.json; case numbers are private locators, never public report rows.",
        "",
        "| Primary explanation | Required affirmative inspections/evidence |",
        "|---|---|",
    ]
    for explanation, evidence in REQUIRED_EVIDENCE.items():
        lines.append(f"| {explanation.value} | {', '.join(sorted(evidence))} |")
    lines += [
        "",
        "Category meanings:",
        "- tokens_absent: visible relevant text is absent from extracted tokens.",
        "- wording_not_supported: a visible tokenized header uses labels outside frozen aliases.",
        "- geometry_or_row_grouping: recognizable labels are split, rotated, reordered or merged.",
        "- continuation_page: verified prior-page table continues without a repeated header.",
        "- document_not_invoice: source and type annotation establish a non-invoice document.",
        "- annotation_or_coordinate_mismatch: checked group/page/normalization does not align.",
        "- other_or_uncertain: competing, insufficient or uninterpretable evidence.",
        "- detected_header_verified: the detected row is a real, visually verified header.",
        "",
        "No empty primary label is counted as inspected or as a confirmed cause.",
    ]
    with (root / "RUBRIC.md").open("x", encoding="utf-8") as output:
        output.write("\n".join(lines) + "\n")


def _box(field: Any) -> dict[str, Any]:
    return {
        "page": field.page,
        "line_item_id": field.line_item_id,
        "fieldtype": field.fieldtype,
        "text": field.text,
        "bbox": [field.bbox.left, field.bbox.top, field.bbox.right, field.bbox.bottom],
    }


def _review_assets(
    root: Path,
    case: int,
    pair: PairedGroup,
    example: Any,
    texts: dict[str, DocumentText],
) -> None:
    import pymupdf

    pdf_path = example.document.data_paths.pdf_path(example.document_id)
    group = grouped_fields(example.document.annotation.li_fields)[(pair.key[1], pair.key[2])]
    directory = root / f"case-{case:03d}"
    directory.mkdir()
    with pymupdf.open(stream=pdf_path.read_bytes(), filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
        page_number = pair.key[1]
        for number in {page_number, max(0, page_number - 1)}:
            page = pdf[number]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6))  # type: ignore[no-untyped-call]
            pixmap.save(directory / ("page.png" if number == page_number else "previous-page.png"))
        _write_private(
            directory / "annotations.json",
            {
                "document_type": str(example.document.annotation.document_type),
                "selected_group": [_box(field) for field in group],
                "page_lir": [
                    _box(f) for f in example.document.annotation.li_fields if f.page == page_number
                ],
                "pdf_rotation": pdf[page_number].rotation,
                "rendered_page_size": [pdf[page_number].rect.width, pdf[page_number].rect.height],
                "annotation_image_size": list(
                    example.document.annotation.page_image_size_at_200dpi(page_number)
                ),
            },
        )
    for mode, text in texts.items():
        selected_pages = [p for p in text.pages if p.page in {pair.key[1], pair.key[1] - 1}]
        _write_private(
            directory / f"{mode}.json",
            {
                "pages": [p.model_dump(mode="json") for p in selected_pages],
                "observation": asdict(next(o for o in pair.observations if o.mode == mode)),
            },
        )


def prepare(args: Any, repository: Path) -> None:
    manifest = load_sample_manifest(args.sample_manifest)
    if len(manifest.document_ids) != 500 or len(set(manifest.document_ids)) != 500:
        raise ValueError("Use the fixed unique 500-document validation manifest")
    require_ocr_runtime(inspect_ocr_runtime())
    root = private_output(args.private_dir, repository, fresh=True)
    cache = private_output(args.cache_dir, repository, fresh=True)
    adapter = DocileDatasetAdapter()
    examples: list[Any] = adapter.load_examples(
        args.dataset_path, args.sample_manifest, DocileEvaluationMode.PRECOMPUTED_OCR
    )
    if len(examples) != 500:
        raise ValueError("Full 500-document coverage is required")
    observations: list[Observation] = []
    missing_ids = 0
    for index, example in enumerate(examples):
        fields = example.document.annotation.li_fields
        missing_ids += sum(f.line_item_id is None for f in fields)
        for mode in MODES:
            if mode == "precomputed_ocr":
                text = document_text_from_docile_ocr(example.document)
            else:
                pdf = example.document.data_paths.pdf_path(example.document_id).read_bytes()
                text = adapter.text_extractor.extract(pdf, "application/pdf")
            trace = trace_line_parser(text, [])
            observations.extend(
                observe_groups(
                    example.document_id,
                    str(example.document.annotation.document_type),
                    mode,
                    trace,
                    fields,
                    len(text.pages),
                )
            )
            _write_private(cache / f"{index:04d}-{mode}.json", text.model_dump(mode="json"))
        if (index + 1) % 50 == 0:
            print(f"Prepared paired observations: {index + 1}/500", flush=True)
    pairs = pair_groups(observations)
    selected = select_groups(
        pairs,
        seed=args.seed,
        misses=args.misses,
        controls=args.controls,
        per_document=args.per_document,
    )
    _write_private(
        root / "inventory.json",
        {
            "observations": [asdict(o) for o in observations],
            "selection": [list(pair.key) for pair in selected],
            "seed": args.seed,
            "misses": args.misses,
            "controls": args.controls,
            "per_document": args.per_document,
            "scanned_documents": len(examples),
            "annotation_fields_missing_line_item_id": missing_ids,
        },
    )
    _write_private(root / "reviews.json", review_template(selected))
    _private_rubric(root)
    lookup = {example.document_id: (index, example) for index, example in enumerate(examples)}
    for case, pair in enumerate(selected):
        index, example = lookup[pair.key[0]]
        texts = {
            mode: DocumentText.model_validate_json(
                (cache / f"{index:04d}-{mode}.json").read_text(encoding="utf-8")
            )
            for mode in MODES
        }
        _review_assets(root, case, pair, example, texts)
    print(
        f"Private review prepared: {len(selected)} paired groups; no explanations assigned.",
        flush=True,
    )


def export(args: Any, repository: Path) -> None:
    root = private_output(args.private_dir, repository, fresh=False)
    inventory = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    pairs = pair_groups([Observation(**item) for item in inventory["observations"]])
    by_key = {pair.key: pair for pair in pairs}
    selected = [by_key[tuple(key)] for key in inventory["selection"]]
    expected = select_groups(
        pairs,
        seed=inventory["seed"],
        misses=inventory["misses"],
        controls=inventory["controls"],
        per_document=inventory["per_document"],
    )
    if [p.key for p in expected] != [p.key for p in selected]:
        raise ValueError("Private selection does not reproduce from saved method")
    report = aggregate_audit(
        pairs,
        selected,
        json.loads((root / "reviews.json").read_text(encoding="utf-8")),
        seed=inventory["seed"],
        per_document=inventory["per_document"],
        requested_misses=inventory["misses"],
        requested_controls=inventory["controls"],
    )
    report["scanned_document_denominator"] = int(inventory["scanned_documents"])
    report["annotation_fields_missing_line_item_id"] = int(
        inventory["annotation_fields_missing_line_item_id"]
    )
    output = aggregate_output(args.output_dir, repository)
    write_aggregate(output, report)
    print("Wrote aggregate-only qualitative audit; no private cases exported.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect = subparsers.add_parser("prepare")
    collect.add_argument("--dataset-path", type=Path, required=True)
    collect.add_argument("--sample-manifest", type=Path, required=True)
    collect.add_argument("--private-dir", type=Path, required=True)
    collect.add_argument("--cache-dir", type=Path, required=True)
    collect.add_argument("--seed", type=int, default=1205)
    collect.add_argument("--misses", type=int, default=40)
    collect.add_argument("--controls", type=int, default=8)
    collect.add_argument("--per-document", type=int, default=2)
    publish = subparsers.add_parser("export")
    publish.add_argument("--private-dir", type=Path, required=True)
    publish.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repository = Path.cwd()
    try:
        if args.command == "prepare":
            prepare(args, repository)
        else:
            export(args, repository)
    except Exception:
        # Dataset exceptions can contain IDs, text or host paths: never emit their repr/traceback.
        raise SystemExit("Audit failed validation; no private details are printed.") from None


if __name__ == "__main__":
    main()
