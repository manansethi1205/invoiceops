"""Offline private financial-role review workflow. Routine logs contain counts only."""

import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from invoiceops.evaluation.financial_role_audit import (
    Selection,
    aggregate_financial,
    blank_pass,
    blind_order,
    fingerprint,
    read_pass,
    seal_pass,
    select_financial_groups,
    verify_seal,
    write_public,
)
from invoiceops.evaluation.header_miss_audit import (
    MODES,
    Observation,
    _no_links,
    aggregate_output,
    pair_groups,
    private_output,
)
from invoiceops.schemas.extraction import DocumentText
from scripts.audit_docile_header_misses import _review_assets, _write_private

RUBRIC = """# PRIVATE financial-role rubric

Source material, labels, pass mappings and notes must stay private. Reviewer-facing folders
contain source pages and tokens only: no first-audit labels, annotations, header-stage signals,
selection tiers or other-pass judgments. Blinding is a workflow boundary, not an OS security
boundary; source familiarity and memory cannot be erased.

For each mode inspect the source and that mode's tokens. Visually confirm invoice yes/no/unknown;
DocILE's invoice stratum is only a sampling label. Classify genuine item table, summary, list,
none or unknown. A description-and-charge table can be an item table while quantity or unit
price is absent. Record observable description, quantity, unit price, printed line total as
present/absent/unknown/competing. Printed rate alone is not automatically a unit price.
An empty financial column supplies a heading, not a financial field value; keep its value
absent/unknown. Classify source-visible roles in the selected page/table context; this is
not an annotation-row field-accuracy review. Sampling groups sharing a page repeat context.
No role or amount may be inferred from arithmetic, multiplied values, annotation labels or
cross-mode assumptions. Missing roles remain absent/unknown; net/tax/gross require printed
context. Distinguish printed net, printed tax, printed gross, summary total, competing,
unknown or none. Multiple amount signals are allowed and do not imply one canonical role.

Choose a primary barrier and optionally competing barriers: missing tokens, unsupported
labels, geometry, ambiguous financial roles, no item table, not visually invoice, clear
explicit roles, unresolved. Unsupported labels require visible tokens and checking frozen
aliases; geometry requires source/token inspection; token loss requires visible missing
text. An absent financial role is not automatically an alias or geometry defect. Genuine
item table does not establish safe extraction or payable amounts. Use unresolved for evidence
that cannot support a primary explanation. Never claim an uninspected case as resolved.

Use two sealed passes. Pass two must not inspect pass-one labels. Same-reviewer repeat is
not independent inter-rater reliability. After both passes are sealed, adjudicate every
mode observation explicitly: confirmed agreement, resolved disagreement, or retained
uncertainty. Explain competing evidence privately; do not silently copy or average labels.
Inspection and explicit adjudication are required even when passes agree. Export only
allowlisted aggregates. This qualitative sample is observed development data, not holdout.
"""


def read_private(path: Path) -> Any:
    _no_links(path)
    return json.loads(path.read_text(encoding="utf-8"))


def selection_from_inventory(root: Path) -> Selection:
    data = read_private(root / "inventory.json")
    pairs = pair_groups([Observation(**o) for o in data["observations"]])
    selection = select_financial_groups(
        pairs,
        {tuple(k) for k in data["first_keys"]},
        {tuple(k) for k in data["unresolved_keys"]},
        **data["options"],
    )
    if [list(p.key) for p in selection.pairs] != data["selection"]:
        raise ValueError("Private selection does not reproduce")
    if selection.accounting != data["accounting"]:
        raise ValueError("Private selection accounting changed")
    return selection


def create_blind_pass(root: Path, selection: Selection, number: int) -> None:
    if number not in {1, 2}:
        raise ValueError("Two review passes only")
    if number == 2:
        verify_seal(root, 1)
    directory = root / f"pass-{number}"
    _no_links(directory)
    directory.mkdir()
    order = blind_order(selection, number, selection.accounting["seed"])
    for slot, case in enumerate(order):
        source = root / "assets" / f"case-{case:03d}"
        target = directory / f"slot-{slot:03d}"
        target.mkdir()
        for name in ("page.png", "previous-page.png", "end_to_end.json", "precomputed_ocr.json"):
            path = source / name
            _no_links(path)
            if path.exists():
                shutil.copyfile(path, target / name)
    _write_private(directory / "reviews.json", blank_pass(selection, number))
    (directory / "RUBRIC.md").write_text(RUBRIC, encoding="utf-8")


def prepare(args: Any, repository: Path) -> None:
    first_root = private_output(args.first_audit, repository, fresh=False)
    first = read_private(first_root / "inventory.json")
    if first["scanned_documents"] != 500:
        raise ValueError("Require the frozen 500-document inventory")
    pairs = pair_groups([Observation(**o) for o in first["observations"]])
    first_keys = {tuple(k) for k in first["selection"]}
    labels = read_private(first_root / "reviews.json")
    unresolved = {
        tuple(first["selection"][r["case"]]) for r in labels if r["primary"] == "other_or_uncertain"
    }
    options = {
        "seed": args.seed,
        "fresh_misses": args.fresh_misses,
        "disagreements": args.disagreements,
        "controls": args.controls,
        "per_document": args.per_document,
    }
    selected = select_financial_groups(pairs, first_keys, unresolved, **options)
    root = private_output(args.private_dir, repository, fresh=True)
    _write_private(
        root / "inventory.json",
        {
            "observations": [asdict(o) for p in pairs for o in p.observations],
            "first_keys": sorted(first_keys),
            "unresolved_keys": sorted(unresolved),
            "options": options,
            "selection": [list(p.key) for p in selected.pairs],
            "accounting": selected.accounting,
        },
    )
    assets = root / "assets"
    assets.mkdir()
    prior_lookup = {tuple(k): i for i, k in enumerate(first["selection"])}
    needed = [p for p in selected.pairs if p.key not in prior_lookup]
    texts_by_doc: dict[str, dict[str, DocumentText]] = {}
    examples: dict[str, Any] = {}
    if needed:
        from invoiceops.evaluation.adapters.docile import (
            DocileDatasetAdapter,
            DocileEvaluationMode,
            document_text_from_docile_ocr,
            load_sample_manifest,
        )
        from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime, require_ocr_runtime

        require_ocr_runtime(inspect_ocr_runtime())
        manifest = load_sample_manifest(args.sample_manifest)
        if len(set(manifest.document_ids)) != 500:
            raise ValueError("Require fixed 500-document manifest")
        adapter = DocileDatasetAdapter()
        loaded = adapter.load_examples(
            args.dataset_path, args.sample_manifest, DocileEvaluationMode.PRECOMPUTED_OCR
        )
        if len(loaded) != 500:
            raise ValueError("Require all 500 validation documents")
        examples = {e.document_id: e for e in loaded}
        for p in needed:
            if p.key[0] not in texts_by_doc:
                example = examples[p.key[0]]
                pdf = example.document.data_paths.pdf_path(example.document_id).read_bytes()
                texts_by_doc[p.key[0]] = {
                    "end_to_end": adapter.text_extractor.extract(pdf, "application/pdf"),
                    "precomputed_ocr": document_text_from_docile_ocr(example.document),
                }
    for case, pair in enumerate(selected.pairs):
        if pair.key in prior_lookup:
            source = first_root / f"case-{prior_lookup[pair.key]:03d}"
            target = assets / f"case-{case:03d}"
            target.mkdir()
            for name in ("page.png", "previous-page.png"):
                _no_links(source / name)
                if (source / name).exists():
                    shutil.copyfile(source / name, target / name)
            for mode in MODES:
                data = read_private(source / (mode + ".json"))
                _write_private(
                    target / (mode + ".json"), {"pages": data["pages"], "used_ocr": True}
                )
        else:
            _review_assets(assets, case, pair, examples[pair.key[0]], texts_by_doc[pair.key[0]])
            target = assets / f"case-{case:03d}"
            (target / "annotations.json").unlink()
            for mode in MODES:
                path = target / (mode + ".json")
                data = read_private(path)
                path.write_text(
                    json.dumps({"pages": data["pages"], "used_ocr": True}), encoding="utf-8"
                )
    create_blind_pass(root, selected, 1)
    print(
        f"Prepared {len(selected.pairs)} invoice-stratum pairs; first blind pass only.", flush=True
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect = sub.add_parser("prepare")
    for name in ("first-audit", "private-dir", "dataset-path", "sample-manifest"):
        collect.add_argument("--" + name, type=Path, required=True)
    for name, default in (
        ("seed", 2110),
        ("fresh-misses", 12),
        ("disagreements", 6),
        ("controls", 4),
        ("per-document", 2),
    ):
        collect.add_argument("--" + name, type=int, default=default)
    for command in ("seal", "second-pass", "adjudication-template", "export"):
        p = sub.add_parser(command)
        p.add_argument("--private-dir", type=Path, required=True)
        if command == "seal":
            p.add_argument("--pass-number", type=int, choices=(1, 2), required=True)
        if command == "export":
            p.add_argument("--output-dir", type=Path, required=True)
            p.add_argument(
                "--reviewer-source", choices=("assistant", "human_declared"), default="assistant"
            )
            p.add_argument(
                "--reviewer-kind",
                choices=("same_reviewer_blinded_repeat", "two_independent_reviewers"),
                default="same_reviewer_blinded_repeat",
            )
    args = parser.parse_args()
    repository = Path.cwd()
    try:
        if args.command == "prepare":
            prepare(args, repository)
            return
        root = private_output(args.private_dir, repository, fresh=False)
        selection = selection_from_inventory(root)
        if args.command == "seal":
            if args.pass_number == 2:
                verify_seal(root, 1)
            seal_pass(root, selection, args.pass_number)
        elif args.command == "second-pass":
            create_blind_pass(root, selection, 2)
        else:
            verify_seal(root, 1)
            verify_seal(root, 2)
            first = read_private(root / "pass-1/reviews.json")
            second = read_private(root / "pass-2/reviews.json")
            if args.command == "adjudication-template":
                a, b = read_pass(selection, 1, first), read_pass(selection, 2, second)
                comparison = [
                    {
                        "case": i,
                        "mode": m,
                        "pass_1": a[(i, m)].model_dump(mode="json"),
                        "pass_2": b[(i, m)].model_dump(mode="json"),
                        "different": fingerprint(a[(i, m)]) != fingerprint(b[(i, m)]),
                    }
                    for i in range(len(selection.pairs))
                    for m in MODES
                ]
                _write_private(root / "private-comparison.json", comparison)
                _write_private(
                    root / "adjudications.json",
                    [
                        {"case": i, "mode": m, "assessment": None, "resolution": None, "notes": ""}
                        for i in range(len(selection.pairs))
                        for m in MODES
                    ],
                )
            else:
                rows = read_private(root / "adjudications.json")
                report = aggregate_financial(
                    selection,
                    first,
                    second,
                    rows,
                    reviewer_kind=args.reviewer_kind,
                    reviewer_source=args.reviewer_source,
                )
                output = aggregate_output(args.output_dir, repository)
                write_public(output, report)
        print("Private review workflow step complete; no case-level values exported.", flush=True)
    except Exception:
        raise SystemExit(
            "Financial-role audit failed; inspect private state without logging source details."
        ) from None


if __name__ == "__main__":
    main()
