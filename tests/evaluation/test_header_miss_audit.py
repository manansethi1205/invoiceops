"""Synthetic tests only: no private DocILE fixtures."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from invoiceops.evaluation.header_miss_audit import (
    MODES,
    REQUIRED_EVIDENCE,
    Explanation,
    Observation,
    aggregate_audit,
    aggregate_output,
    grouped_fields,
    observe_groups,
    pair_groups,
    private_output,
    render_markdown,
    review_template,
    select_groups,
    write_aggregate,
)
from invoiceops.evaluation.line_coverage import annotated_stage_counts, trace_line_parser
from tests.evaluation.test_line_coverage import annotation
from tests.unit.test_line_item_rules import document, table_page


def observations(size: int = 80) -> list[Observation]:
    result = []
    for index in range(size):
        for mode in MODES:
            result.append(
                Observation(
                    f"SYNTHETIC_PRIVATE_ID_{index // 2}",
                    index % 2,
                    index,
                    mode,
                    "invoice" if index % 3 else "other",
                    "first" if index % 2 == 0 else "later",
                    index < 16,
                    index % 4 != 0,
                    ("none", "description_only", "description_line_total", "mixed")[index % 4],
                )
            )
    return result


def test_sampling_reproducible_order_independent_paired_and_capped() -> None:
    pairs = pair_groups(observations())
    selected = select_groups(pairs)
    assert [p.key for p in selected] == [p.key for p in select_groups(list(reversed(pairs)))]
    assert len(selected) == 48
    assert sum(all(o.header_detected for o in p.observations) for p in selected) == 8
    assert all(tuple(o.mode for o in p.observations) == MODES for p in selected)
    assert len({p.key for p in selected}) == 48
    assert all(sum(p.key[0] == q.key[0] for p in selected) <= 2 for q in selected)
    assert [p.key for p in selected] != [p.key for p in select_groups(pairs, seed=7)]


def test_joint_strata_include_both_mode_signals_and_metadata() -> None:
    pairs = pair_groups(observations(2))
    altered = replace(pairs[0].observations[1], token_present=True, signature="mixed")
    changed = pair_groups([pairs[0].observations[0], altered])[0]
    assert changed.stratum != pairs[0].stratum
    assert "end_to_end:" in changed.stratum[2]
    assert "precomputed_ocr:" in changed.stratum[3]
    assert changed.stratum[:2] == ("other", "first")


def test_shortfall_is_explicit_never_breaks_document_cap() -> None:
    pairs = pair_groups(observations(3))
    selected = select_groups(pairs, per_document=1)
    report = aggregate_audit(pairs, selected, [], per_document=1)
    assert report["selected_pairs"] == 2
    assert report["requested_misses"] == 40
    assert report["requested_controls"] == 8
    assert report["selected_miss_pairs"] == 0


@pytest.mark.parametrize(
    "mutation", ["missing", "duplicate", "unsafe_type", "unsafe_signature", "page"]
)
def test_pairing_rejects_incomplete_duplicate_or_unsafe_labels(mutation: str) -> None:
    values = observations(1)
    if mutation == "missing":
        values.pop()
    elif mutation == "duplicate":
        values.append(values[0])
    elif mutation == "unsafe_type":
        values[0] = replace(values[0], document_type="PRIVATE_TEXT")
    elif mutation == "unsafe_signature":
        values[0] = replace(values[0], signature="PRIVATE_TEXT")
    else:
        values[0] = replace(values[0], page_position="PRIVATE_TEXT")
    with pytest.raises(ValueError):
        pair_groups(values)


def test_continuation_page_is_observed_not_automatically_explained() -> None:
    doc = document(
        table_page(0, [(0.25, "First Part", "1", "10", "10")]),
        table_page(1, [(0.25, "Continued Part", "1", "10", "10")], aliases=("", "", "", "")),
    )
    fields = [annotation(0, 9, 0.08, 0.25), annotation(1, 9, 0.08, 0.25)]
    trace = trace_line_parser(doc, [])
    counts = annotated_stage_counts(trace, fields)
    assert counts["annotated_line_page_groups"] == 2
    assert counts["line_groups_stage_header_not_detected_on_page"] == 1
    values = observe_groups("SYNTHETIC_ID", "invoice", MODES[0], trace, fields, 2)
    later = values[1]
    assert not later.header_detected and later.token_present
    assert later.earlier_page_has_header and later.prior_page_has_lir
    assert later.same_line_id_on_other_page
    paired = pair_groups(values + [replace(o, mode=MODES[1]) for o in values])
    report = aggregate_audit(paired, paired, review_template(paired))
    assert report["modes"][MODES[0]]["unreviewed"] == 2
    assert report["modes"][MODES[0]]["primary_explanations"]["continuation_page"] == 0


def test_page_local_ids_missing_ids_and_duplicate_fields() -> None:
    fields = [
        annotation(0, 7, 0.08, 0.25),
        annotation(0, 7, 0.53, 0.25, "line_item_quantity"),
        annotation(1, 7, 0.08, 0.25),
        annotation(0, None, 0.08, 0.5),
    ]
    groups = grouped_fields(fields)
    assert len(groups) == 2 and len(groups[(0, 7)]) == 2
    assert (0, None) not in groups


def test_center_containment_overlap_invalid_coordinate_and_page_edges() -> None:
    doc = document(table_page(0, [(0.25, "Part", "1", "10", "10")]))
    trace = trace_line_parser(doc, [])
    word = next(w for row in trace.rows for w in row.words if w.text == "Part")
    # The annotation intersects the word's left edge but excludes its center.
    edge = annotation(0, 1, word.bbox.x0, word.bbox.y0)
    edge.bbox.right = word.bbox.x0 + (word.bbox.x1 - word.bbox.x0) / 4
    invalid = annotation(0, 2, 3, 0.25)
    wrong_page = annotation(7, 3, 0.08, 0.25)
    nan = annotation(0, 4, 0.08, float("nan"))
    values = observe_groups(
        "SYNTHETIC_ID", "invoice", MODES[0], trace, [edge, invalid, wrong_page, nan], 1
    )
    by_line = {o.line_item_id: o for o in values}
    assert not by_line[1].token_present and by_line[1].overlap_without_center_fields == 1
    assert by_line[2].invalid_box_fields == by_line[3].invalid_box_fields == 1
    assert by_line[4].invalid_box_fields == 1


def test_center_boundary_is_inclusive_but_never_a_confirmed_coordinate_cause() -> None:
    doc = document(table_page(0, [(0.25, "Part", "1", "10", "10")]))
    trace = trace_line_parser(doc, [])
    word = next(w for row in trace.rows for w in row.words if w.text == "Part")
    field = annotation(0, 1, (word.bbox.x0 + word.bbox.x1) / 2, word.bbox.y0)
    value = observe_groups("SYNTHETIC_ID", "invoice", MODES[0], trace, [field], 1)[0]
    assert value.token_present


@pytest.mark.parametrize("explanation", list(Explanation))
def test_category_accounting_requires_private_inspection_evidence(explanation: Explanation) -> None:
    pairs = pair_groups(observations(1))
    reviews = review_template(pairs)
    reviews[0].update(primary=explanation.value, evidence=sorted(REQUIRED_EVIDENCE[explanation]))
    report = aggregate_audit(pairs, pairs, reviews)
    values = report["modes"][MODES[0]]
    assert sum(values["primary_explanations"].values()) == values["inspected"] == 1
    assert values["uncertainty_count"] == int(explanation == Explanation.UNCERTAIN)
    reviews[0]["evidence"] = []
    with pytest.raises(ValueError, match="evidence"):
        aggregate_audit(pairs, pairs, reviews)


def test_unreviewed_uncertain_and_confirmed_are_separate() -> None:
    pairs = pair_groups(observations(2))
    reviews = review_template(pairs)
    reviews[0].update(
        primary="other_or_uncertain",
        evidence=sorted(REQUIRED_EVIDENCE[Explanation.UNCERTAIN]),
        notes="PRIVATE_TEXT SOURCE_PATH /private-document.pdf",
    )
    report = aggregate_audit(pairs, pairs, reviews)
    first, second = (report["modes"][mode] for mode in MODES)
    assert first["inspected"] == first["unreviewed"] == 1
    assert first["uncertainty_count"] == second["uncertainty_count"] == 2
    exported = json.dumps(report)
    assert "PRIVATE_TEXT" not in exported and "SYNTHETIC_PRIVATE_ID" not in exported
    assert "/private-document.pdf" not in exported
    assert report["jointly_reviewed_pair_denominator"] == 0


def test_paired_comparison_denominators() -> None:
    values = observations(1)
    values[1] = replace(values[1], header_detected=False, token_present=True)
    pairs = pair_groups(values)
    report = aggregate_audit(pairs, pairs, [])
    assert report["paired_denominator"] == 1
    assert report["header_transitions_end_to_end_to_precomputed"] == {"1->0": 1}
    assert report["paired_disagreements"]["header_detection"] == 1
    assert report["paired_disagreements"]["token_presence"] == 1


def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def test_private_guard_ignored_paths_and_overwrite_protection(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    target = repo / "work/docile-header-audit-private/new"
    assert private_output(target, repo, fresh=True) == target.resolve()
    assert private_output(target, repo, fresh=False) == target.resolve()
    with pytest.raises(FileExistsError):
        private_output(target, repo, fresh=True)
    with pytest.raises(ValueError):
        private_output(repo / "docs/private", repo, fresh=True)
    subprocess.run(["git", "add", "--force", str(target.parent)], cwd=repo, check=True)
    # Track a synthetic file, then reject reopening its private root.
    (target / "synthetic.txt").write_text("synthetic", encoding="utf-8")
    subprocess.run(["git", "add", "--force", str(target)], cwd=repo, check=True)
    with pytest.raises(ValueError, match="untracked"):
        private_output(target, repo, fresh=False)


def test_output_symlink_and_aggregate_overwrite_guards(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    output = repo / "evals/reports/docile/new"
    output = aggregate_output(output, repo)
    pairs = pair_groups(observations(1))
    report = aggregate_audit(pairs, pairs, [])
    write_aggregate(output, report)
    assert "SYNTHETIC_PRIVATE_ID" not in (output / "report.json").read_text()
    with pytest.raises(FileExistsError):
        write_aggregate(output, report)
    with pytest.raises(FileExistsError):
        aggregate_output(output, repo)
    with pytest.raises(ValueError):
        aggregate_output(repo / "docs/report", repo)
    link = repo / "linked"
    try:
        link.symlink_to(repo / "evals", target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="links"):
        aggregate_output(link / "reports/docile/other", repo)


def test_export_rejects_accidentally_added_private_strings(tmp_path: Path) -> None:
    report = aggregate_audit([], [], [])
    report["private_case"] = "PRIVATE_SENTINEL"
    with pytest.raises(ValueError, match="allowlisted"):
        write_aggregate(tmp_path, report)
    assert not list(tmp_path.iterdir())


def test_docile_adapter_keeps_normalized_coordinates_and_zero_based_pages() -> None:
    from types import SimpleNamespace

    from invoiceops.evaluation.adapters.docile import document_text_from_docile_ocr

    raw = SimpleNamespace(
        text="Synthetic", bbox=SimpleNamespace(left=0.1, top=0.2, right=0.3, bottom=0.22)
    )
    fake = SimpleNamespace(
        page_count=2,
        ocr=SimpleNamespace(get_all_words=lambda page, snapped=False: [raw]),
        annotation=SimpleNamespace(page_image_size_at_200dpi=lambda page: [2000, 3000]),
    )
    text = document_text_from_docile_ocr(fake)
    assert [page.page for page in text.pages] == [0, 1]
    assert text.pages[1].width == 2000 and text.pages[1].height == 3000
    word = text.pages[1].words[0]
    assert word.page == 1 and word.bbox.x0 == 0.1 and word.bbox.y0 == 0.2
    field = annotation(1, 1, 0.1, 0.2)
    values = observe_groups(
        "SYNTHETIC_ID", "invoice", MODES[1], trace_line_parser(text, []), [field], 2
    )
    assert values[0].token_present and values[0].invalid_box_fields == 0


def test_cli_errors_do_not_print_private_exception_details(monkeypatch, capsys) -> None:
    from scripts import audit_docile_header_misses as runner

    def fail(*args):
        raise ValueError("PRIVATE_ID PRIVATE_SOURCE_TEXT C:/private-source.pdf")

    monkeypatch.setattr(runner, "prepare", fail)
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit",
            "prepare",
            "--dataset-path",
            "private-dataset",
            "--sample-manifest",
            "manifest",
            "--private-dir",
            "private",
            "--cache-dir",
            "cache",
        ],
    )
    with pytest.raises(SystemExit) as failure:
        runner.main()
    assert "PRIVATE_ID" not in str(failure.value)
    assert "PRIVATE" not in capsys.readouterr().out


def test_tax_invoice_taxonomy_is_an_invoice_stratum() -> None:
    doc = document(table_page(0, [(0.25, "Part", "1", "10", "10")]))
    obs = observe_groups(
        "SYNTHETIC_ID",
        "tax_invoice",
        MODES[0],
        trace_line_parser(doc, []),
        [annotation(0, 1, 0.08, 0.25)],
        1,
    )
    assert obs[0].document_type == "invoice"


def test_private_previews_accept_docile_byte_paths(tmp_path: Path) -> None:
    from types import SimpleNamespace

    import pymupdf

    from scripts.audit_docile_header_misses import _review_assets

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 60), "Synthetic Item Qty Amount")
        data = pdf.tobytes()
    pairs = pair_groups(observations(1))
    field = annotation(0, 0, 0.08, 0.25)
    example = SimpleNamespace(
        document_id="SYNTHETIC_ID",
        document=SimpleNamespace(
            data_paths=SimpleNamespace(
                pdf_path=lambda ignored: SimpleNamespace(read_bytes=lambda: data)
            ),
            annotation=SimpleNamespace(
                li_fields=[field],
                document_type="tax_invoice",
                page_image_size_at_200dpi=lambda ignored: [1653, 2338],
            ),
        ),
    )
    text = document(table_page(0, [(0.25, "Part", "1", "10", "10")]))
    _review_assets(tmp_path, 0, pairs[0], example, {mode: text for mode in MODES})
    assert (tmp_path / "case-000/page.png").exists()
    assert (tmp_path / "case-000/annotations.json").exists()
    assert (tmp_path / "case-000/end_to_end.json").exists()


def test_document_type_review_counts_reconcile_without_private_case_keys() -> None:
    pairs = pair_groups(observations(4))
    report = aggregate_audit(pairs, pairs, review_template(pairs))
    for mode in MODES:
        counts = report["modes"][mode]["review_by_document_type"]
        assert sum(sum(categories.values()) for categories in counts.values()) == 4
        assert counts["other"]["unreviewed"] == 2
        assert counts["invoice"]["unreviewed"] == 2


def test_markdown_per_mode_misses_and_uncertainty_denominators_reconcile() -> None:
    values = observations(48)
    for index, observation in enumerate(values):
        group = index // 2
        detected = group < 8 or (
            8 <= group < 12 if observation.mode == "end_to_end" else 12 <= group < 16
        )
        values[index] = replace(observation, header_detected=detected)
    pairs = pair_groups(values)
    reviews = review_template(pairs)
    uncertain = dict.fromkeys(MODES, 0)
    targets = {"end_to_end": 12, "precomputed_ocr": 15}
    for review in reviews:
        mode = review["mode"]
        observation = next(o for o in pairs[review["case"]].observations if o.mode == mode)
        if observation.header_detected:
            explanation = Explanation.DETECTED
        elif uncertain[mode] < targets[mode]:
            explanation = Explanation.UNCERTAIN
            uncertain[mode] += 1
        else:
            explanation = Explanation.WORDING
        review.update(primary=explanation.value, evidence=list(REQUIRED_EVIDENCE[explanation]))
    report = aggregate_audit(pairs, pairs, reviews)
    markdown = render_markdown(report)
    assert report["selected_miss_pairs"] == 40
    assert report["selected_control_pairs"] == 8
    for mode in MODES:
        detection = report["modes"][mode]["selected_strata"]["header_detection"]
        assert detection["detected"] + detection["not_detected"] == 48
        assert detection["not_detected"] == 36
        assert f"| {mode} | 48 | 12 | 36 | {targets[mode]}/36 |" in markdown
    assert "at least one mode missed" in markdown
    assert "4 pairs were detected end-to-end" in markdown
    assert "4 were detected in precomputed OCR" in markdown
    assert "nonrepresentative and was reviewed by one person" in markdown
    report["modes"]["end_to_end"]["selected_strata"]["header_detection"]["not_detected"] = 40
    with pytest.raises(ValueError, match="denominators"):
        render_markdown(report)
