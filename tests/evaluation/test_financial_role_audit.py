"""Synthetic private-review and aggregate tests; no DocILE content."""

import json

import pytest
from pydantic import ValidationError

from invoiceops.evaluation.financial_role_audit import (
    EVIDENCE,
    MODES,
    Assessment,
    Barrier,
    aggregate_financial,
    blank_pass,
    blind_order,
    read_pass,
    seal_pass,
    select_financial_groups,
    validate_public,
    verify_seal,
    write_public,
)
from invoiceops.evaluation.header_miss_audit import (
    Observation,
    aggregate_output,
    pair_groups,
    private_output,
)
from scripts.adjudicate_docile_financial_roles import create_blind_pass


def universe():
    values = []
    for i in range(80):
        for mode in MODES:
            values.append(
                Observation(
                    f"SYNTHETIC_SECRET_{i // 2}",
                    i % 2,
                    i,
                    mode,
                    "other" if i >= 76 else "invoice",
                    "first" if i % 2 == 0 else "later",
                    i >= 60 or (40 <= i < 60 and mode == "precomputed_ocr"),
                    True,
                    "description_only" if i % 2 else "description_line_total",
                )
            )
    return pair_groups(values)


def sample(**kwargs):
    pairs = universe()
    first = {p.key for p in pairs if p.key[2] < 6}
    unresolved = {p.key for p in pairs if p.key[2] < 4}
    return select_financial_groups(pairs, first, unresolved, **kwargs)


def assessment(primary=Barrier.UNKNOWN, **kwargs):
    data = {
        "visual_invoice": "yes",
        "table": "item_table",
        "primary": primary.value,
        "roles": dict.fromkeys(
            ("description", "quantity", "unit_price", "printed_line_total"), "unknown"
        ),
        "amounts": ["unknown"],
        "competing": [],
        "evidence": sorted(
            {"source_inspected", "tokens_inspected", "roles_checked_without_arithmetic"}
            | EVIDENCE[primary]
        ),
        "notes": "SYNTHETIC PRIVATE TEXT C:/private/path",
    }
    data.update(kwargs)
    return Assessment.model_validate(data).model_dump(mode="json")


def passes(selection, primary=Barrier.UNKNOWN):
    result = []
    for number in (1, 2):
        rows = blank_pass(selection, number)
        for row in rows:
            row["assessment"] = assessment(primary)
        result.append(rows)
    return result


def adjudications(selection, primary=Barrier.UNKNOWN):
    return [
        {
            "case": i,
            "mode": m,
            "assessment": assessment(primary),
            "resolution": "retained_uncertainty"
            if primary == Barrier.UNKNOWN
            else "confirmed_agreement",
            "notes": "SYNTHETIC PRIVATE NOTE",
        }
        for i in range(len(selection.pairs))
        for m in MODES
    ]


def test_selection_deterministic_nonoverlap_pairing_caps_and_accounting():
    chosen = sample()
    other = select_financial_groups(
        list(reversed(universe())),
        {p.key for p in universe() if p.key[2] < 6},
        {p.key for p in universe() if p.key[2] < 4},
    )
    assert [p.key for p in chosen.pairs] == [p.key for p in other.pairs]
    assert chosen.accounting["achieved"] == {
        "prior_unresolved": 4,
        "fresh_misses": 12,
        "ocr_disagreements": 6,
        "detected_controls": 4,
    }
    assert len(chosen.pairs) == 26 and len({p.key for p in chosen.pairs}) == 26
    first_docs = {p.key[0] for p in universe() if p.key[2] < 6}
    for p, tier in zip(chosen.pairs, chosen.tiers, strict=True):
        assert p.observations[0].document_type == "invoice"
        assert tuple(o.mode for o in p.observations) == MODES
        if tier != "prior_unresolved":
            assert p.key[0] not in first_docs
        assert sum(q.key[0] == p.key[0] for q in chosen.pairs) <= 2
    assert [p.key for p in chosen.pairs] != [p.key for p in sample(seed=9).pairs]


def test_shortfall_exclusions_do_not_relax_cap():
    s = sample(per_document=1, fresh_misses=100, disagreements=100, controls=100)
    assert s.accounting["shortfall"]["prior_unresolved"] == 2
    assert sum(s.accounting["achieved"].values()) == len(s.pairs)
    assert s.accounting["non_invoice_stratum_exclusions"] == 4
    assert len({p.key[0] for p in s.pairs}) == len(s.pairs)
    with pytest.raises(ValueError):
        sample(controls=0)


def test_blind_templates_have_no_prior_labels_tiers_keys_or_observations():
    s = sample()
    assert blind_order(s, 1) != blind_order(s, 2)
    for n in (1, 2):
        rows = blank_pass(s, n)
        assert all(
            set(r) == {"slot", "mode", "assessment"} and r["assessment"] is None for r in rows
        )
        text = json.dumps(rows)
        assert "SYNTHETIC_SECRET" not in text and "prior_unresolved" not in text
    rows = blank_pass(s, 1)
    rows[0]["prior_primary"] = "token_loss"
    with pytest.raises(ValueError, match="keys"):
        read_pass(s, 1, rows)


def test_seals_second_pass_gate_and_tamper_detection(tmp_path):
    s = sample()
    root = tmp_path
    with pytest.raises(FileNotFoundError):
        create_blind_pass(root, s, 2)
    (root / "pass-1").mkdir()
    first, _ = passes(s)
    path = root / "pass-1/reviews.json"
    path.write_text(json.dumps(first))
    seal_pass(root, s, 1)
    verify_seal(root, 1)
    with pytest.raises(FileExistsError):
        seal_pass(root, s, 1)
    path.write_text(json.dumps(blank_pass(s, 1)))
    with pytest.raises(ValueError, match="modified"):
        verify_seal(root, 1)


def test_blind_assets_omit_annotation_and_baseline(tmp_path):
    s = sample()
    for i in range(len(s.pairs)):
        source = tmp_path / "assets" / f"case-{i:03d}"
        source.mkdir(parents=True)
        (source / "page.png").write_bytes(b"synthetic image")
        (source / "end_to_end.json").write_text('{"pages": []}')
        (source / "annotations.json").write_text("SYNTHETIC_SECRET")
    create_blind_pass(tmp_path, s, 1)
    assert not list((tmp_path / "pass-1").rglob("annotations.json"))
    assert not list((tmp_path / "pass-1").rglob("inventory.json"))
    assert "SYNTHETIC_SECRET" not in (tmp_path / "pass-1/reviews.json").read_text()


def test_required_evidence_financial_ambiguity_and_scope():
    with pytest.raises(ValidationError):
        assessment(Barrier.TOKEN_LOSS, evidence=[])
    with pytest.raises(ValidationError):
        assessment(Barrier.SCOPE, visual_invoice="unknown")
    with pytest.raises(ValidationError):
        assessment(Barrier.NO_TABLE, table="unknown")
    with pytest.raises(ValidationError):
        assessment(Barrier.CLEAR)
    with pytest.raises(ValidationError):
        assessment(roles={"printed_line_total": "inferred"})
    data = assessment(Barrier.AMBIGUITY, amounts=["competing", "unknown"], competing=["geometry"])
    assert data["roles"]["printed_line_total"] == "unknown"


def test_accounting_uncertainty_and_paired_changes():
    s = sample()
    a, b = passes(s)
    final = adjudications(s)
    report = aggregate_financial(s, a, b, final)
    for mode in MODES:
        v = report["modes"][mode]
        assert v["adjudicated"] == v["unresolved_count"] == len(s.pairs)
        assert v["actual_header_misses"] + v["detected_headers"] == len(s.pairs)
        assert sum(v["primary_barriers"].values()) == v["adjudicated"]
        assert v["pass_any_classification_disagreement"] == 0
    assert report["next_choice"] == "unresolved"
    assert report["reviewer_kind"] == "same_reviewer_blinded_repeat"
    empty = aggregate_financial(s, blank_pass(s, 1), blank_pass(s, 2), [])
    assert empty["modes"]["end_to_end"]["unresolved_count"] == len(s.pairs)
    assert empty["jointly_adjudicated_pair_denominator"] == 0


def test_disagreement_explicit_adjudication_and_role_changes():
    s = sample()
    a, b = passes(s, Barrier.AMBIGUITY)
    # Change same group in second pass, mapped by anonymous slot.
    case = blind_order(s, 1)[0]
    slot = blind_order(s, 2).index(case)
    row = next(r for r in b if r["slot"] == slot and r["mode"] == "end_to_end")
    row["assessment"] = assessment(Barrier.TOKEN_LOSS)
    final = adjudications(s, Barrier.AMBIGUITY)
    item = next(r for r in final if r["case"] == case and r["mode"] == "end_to_end")
    with pytest.raises(ValueError, match="conceal"):
        aggregate_financial(s, a, b, final)
    item["resolution"] = "resolved_disagreement"
    item["assessment"] = assessment(Barrier.TOKEN_LOSS)
    report = aggregate_financial(s, a, b, final)
    assert report["modes"]["end_to_end"]["pass_primary_disagreement"] == 1
    assert report["paired_primary_changes"] == 1
    assert report["adjudication_resolution_counts"]["resolved_disagreement"] == 1


def test_public_allowlist_privacy_and_overwrite(tmp_path):
    s = sample()
    a, b = passes(s)
    report = aggregate_financial(s, a, b, adjudications(s))
    write_public(tmp_path, report)
    content = (tmp_path / "report.json").read_text() + (tmp_path / "report.md").read_text()
    assert "SYNTHETIC" not in content and "C:/private" not in content
    reloaded = json.loads((tmp_path / "report.json").read_text())
    rebuilt = tmp_path / "rebuilt"
    rebuilt.mkdir()
    write_public(rebuilt, reloaded)
    assert (rebuilt / "report.md").read_text() == (tmp_path / "report.md").read_text()
    with pytest.raises(FileExistsError):
        write_public(tmp_path, report)
    report["case_labels"] = "SYNTHETIC_SECRET"
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(ValueError, match="allowlisted"):
        write_public(fresh, report)
    assert not list(fresh.iterdir())


def test_reuse_output_guards_and_no_parser_mutation(tmp_path):
    import subprocess

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n")
    private = tmp_path / "work/docile-header-audit-private/new"
    private_output(private, tmp_path, fresh=True)
    with pytest.raises(FileExistsError):
        private_output(private, tmp_path, fresh=True)
    with pytest.raises(ValueError):
        private_output(tmp_path / "docs/private", tmp_path, fresh=True)
    out = aggregate_output(tmp_path / "evals/reports/docile/new", tmp_path)
    with pytest.raises(FileExistsError):
        aggregate_output(out, tmp_path)
    from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
    from tests.unit.test_line_item_rules import document, table_page

    source = document(table_page(0, [(0.3, "Synthetic item", "2", "5.00", "10.00")]))
    before = DeterministicInvoiceExtractor().extract(source)
    s = sample()
    a, b = passes(s)
    aggregate_financial(s, a, b, adjudications(s))
    after = DeterministicInvoiceExtractor().extract(source)
    assert before == after


def test_decision_gate_requires_complete_shared_majority_and_pattern_evidence():
    s = sample()
    a, b = passes(s, Barrier.AMBIGUITY)
    final = adjudications(s, Barrier.AMBIGUITY)
    report = aggregate_financial(s, a, b, final)
    assert report["next_choice"] == "ambiguous_financial_roles"
    assert "guarded vision/human-review" in report["next_implementation"]
    incomplete = aggregate_financial(s, a, b, final[:-1])
    assert incomplete["next_choice"] == "unresolved"
    # A geometry count alone cannot establish one repeated, financially explicit pattern.
    a, b = passes(s, Barrier.GEOMETRY)
    report = aggregate_financial(s, a, b, adjudications(s, Barrier.GEOMETRY))
    assert report["next_choice"] == "unresolved"


def test_primary_agreement_can_hide_field_disagreement_and_needs_adjudication():
    s = sample()
    a, b = passes(s, Barrier.AMBIGUITY)
    case = blind_order(s, 1)[0]
    slot = blind_order(s, 2).index(case)
    value = next(r for r in b if r["slot"] == slot and r["mode"] == MODES[0])
    value["assessment"]["roles"]["printed_line_total"] = "competing"
    final = adjudications(s, Barrier.AMBIGUITY)
    item = next(r for r in final if r["case"] == case and r["mode"] == MODES[0])
    with pytest.raises(ValueError, match="conceal"):
        aggregate_financial(s, a, b, final)
    item["assessment"] = value["assessment"]
    item["resolution"] = "resolved_disagreement"
    report = aggregate_financial(s, a, b, final)
    assert report["modes"][MODES[0]]["pass_primary_disagreement"] == 0
    assert report["modes"][MODES[0]]["pass_any_classification_disagreement"] == 1
    assert report["paired_role_changes"]["printed_line_total"] == 1


def test_uninspected_templates_cannot_seal_or_adjudicate(tmp_path):
    s = sample()
    (tmp_path / "pass-1").mkdir()
    (tmp_path / "pass-1/reviews.json").write_text(json.dumps(blank_pass(s, 1)))
    with pytest.raises(ValueError, match="Inspect every"):
        seal_pass(tmp_path, s, 1)
    with pytest.raises(ValueError, match="both inspected"):
        aggregate_financial(s, blank_pass(s, 1), blank_pass(s, 2), adjudications(s))
    a, _ = passes(s)
    with pytest.raises(ValueError, match="Incomplete"):
        read_pass(s, 1, a[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        read_pass(s, 1, [*a, a[0]])


def test_public_numeric_payload_schema_and_markdown_denominators(tmp_path):
    s = sample()
    a, b = passes(s)
    report = aggregate_financial(s, a, b, adjudications(s))
    write_public(tmp_path, report)
    text = (tmp_path / "report.md").read_text()
    for mode in MODES:
        v = report["modes"][mode]
        assert v["unresolved_header_misses"] == v["actual_header_misses"]
        assert f"{mode}: {v['unresolved_header_misses']}/{v['actual_header_misses']}" in text
        assert (
            sum(v["visually_invoice_miss_barriers"].values())
            == v["visually_invoice_miss_denominator"]
        )
    report["selection"]["seed"] = 123.456
    with pytest.raises(ValueError, match="integers"):
        validate_public(report)
    report["selection"]["seed"] = 2110
    report["modes"][MODES[0]]["roles"]["notes"] = 5
    with pytest.raises(ValueError):
        validate_public(report)


def test_existing_markdown_refused_before_json_written(tmp_path):
    s = sample()
    a, b = passes(s)
    (tmp_path / "report.md").write_text("frozen synthetic report")
    with pytest.raises(FileExistsError):
        write_public(tmp_path, aggregate_financial(s, a, b, adjudications(s)))
    assert not (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").read_text() == "frozen synthetic report"


def test_competing_roles_cannot_be_clear_and_assistant_cannot_claim_independence():
    roles = dict.fromkeys(
        ("description", "quantity", "unit_price", "printed_line_total"), "present"
    )
    roles["quantity"] = "competing"
    with pytest.raises(ValidationError, match="unambiguous"):
        assessment(Barrier.CLEAR, roles=roles)
    s = sample()
    a, b = passes(s)
    with pytest.raises(ValueError, match="independence"):
        aggregate_financial(s, a, b, adjudications(s), reviewer_kind="two_independent_reviewers")


def test_nested_asset_links_rejected_before_private_copy(tmp_path):
    s = sample()
    source = tmp_path / "assets/case-000"
    source.mkdir(parents=True)
    secret = tmp_path / "private-secret.png"
    secret.write_bytes(b"SYNTHETIC PRIVATE")
    try:
        (source / "page.png").symlink_to(secret)
    except OSError:
        pytest.skip("Windows symlink permission unavailable")
    with pytest.raises(ValueError, match="links"):
        create_blind_pass(tmp_path, s, 1)
    assert not list((tmp_path / "pass-1").rglob("page.png"))
