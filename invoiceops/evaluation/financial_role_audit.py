"""Private paired invoice financial-role adjudication; evaluation only."""

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from invoiceops.evaluation.header_miss_audit import MODES, PairedGroup, _no_links, _rank


class Barrier(StrEnum):
    TOKEN_LOSS = "token_loss"
    LABELS = "unsupported_labels"
    GEOMETRY = "geometry"
    AMBIGUITY = "ambiguous_financial_roles"
    NO_TABLE = "no_item_table"
    SCOPE = "not_visually_invoice"
    CLEAR = "clear_roles"
    UNKNOWN = "unresolved"


ROLES = ("description", "quantity", "unit_price", "printed_line_total")
ROLE_STATES = ("present", "absent", "unknown", "competing")
VISUAL = ("yes", "no", "unknown")
TABLES = ("item_table", "summary", "list", "none", "unknown")
AMOUNTS = (
    "printed_net",
    "printed_tax",
    "printed_gross",
    "summary_total",
    "competing",
    "unknown",
    "none",
)


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visual_invoice: str = "unknown"
    table: str = "unknown"
    roles: dict[str, str] = Field(default_factory=lambda: dict.fromkeys(ROLES, "unknown"))
    amounts: list[str] = Field(default_factory=lambda: ["unknown"])
    primary: Barrier = Barrier.UNKNOWN
    competing: list[Barrier] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def checked(self) -> "Assessment":
        if self.visual_invoice not in VISUAL or self.table not in TABLES:
            raise ValueError("Unsupported visual classification")
        if set(self.roles) != set(ROLES) or not set(self.roles.values()) <= set(ROLE_STATES):
            raise ValueError("Unsupported role classification")
        if not self.amounts or not set(self.amounts) <= set(AMOUNTS):
            raise ValueError("Unsupported amount classification")
        if len(set(self.amounts)) != len(self.amounts) or len(set(self.competing)) != len(
            self.competing
        ):
            raise ValueError("Duplicate classification")
        needed = {"source_inspected", "tokens_inspected", "roles_checked_without_arithmetic"}
        needed |= EVIDENCE[self.primary]
        if not needed <= set(self.evidence):
            raise ValueError("Required private inspection evidence missing")
        if self.primary == Barrier.SCOPE and self.visual_invoice != "no":
            raise ValueError("Non-invoice explanation requires visual confirmation")
        if self.primary == Barrier.NO_TABLE and self.table not in {"summary", "list", "none"}:
            raise ValueError("No item table requires affirmative visual classification")
        if self.primary == Barrier.CLEAR and (
            self.visual_invoice != "yes"
            or self.table != "item_table"
            or self.roles["description"] != "present"
            or self.roles["printed_line_total"] != "present"
            or not any(self.roles[r] == "present" for r in ("quantity", "unit_price"))
            or "competing" in self.roles.values()
            or "competing" in self.amounts
            or self.competing
        ):
            raise ValueError("Clear roles require an explicit unambiguous item table")
        return self


EVIDENCE = {
    Barrier.TOKEN_LOSS: {"visible_text_missing_from_tokens"},
    Barrier.LABELS: {"printed_labels_checked_against_frozen_aliases"},
    Barrier.GEOMETRY: {"source_and_token_geometry_checked"},
    Barrier.AMBIGUITY: {"competing_or_missing_roles_checked"},
    Barrier.NO_TABLE: {"table_structure_checked"},
    Barrier.SCOPE: {"visual_document_type_checked"},
    Barrier.CLEAR: {"explicit_printed_roles_checked"},
    Barrier.UNKNOWN: set(),
}
TIERS = ("prior_unresolved", "fresh_misses", "ocr_disagreements", "detected_controls")
SCOPE = "500-document observed development data; nonrepresentative qualitative sample, not holdout"
METHOD = (
    "seed-ranked round-robin joint strata; unresolved first; fresh "
    "groups exclude first-audit documents"
)
REVIEW_KINDS = ("same_reviewer_blinded_repeat", "two_independent_reviewers")
DECISION_MATRIX = {
    "token_loss": "bounded OCR/preprocessing experiment",
    "unsupported_labels": "versioned parser experiment after explicit-role confirmation",
    "geometry": "versioned deterministic layout experiment after repeated-layout confirmation",
    "ambiguous_financial_roles": "guarded vision/human-review pilot preserving abstention",
    "no_item_table": "explicit no-item-table abstention and review handoff",
    "not_visually_invoice": "document-scope gate before invoice extraction",
    "clear_roles": "no failure-directed implementation justified",
    "unresolved": "no-go: evidence does not support an implementation category",
}


@dataclass(frozen=True, repr=False)
class Selection:
    pairs: tuple[PairedGroup, ...]
    tiers: tuple[str, ...]
    accounting: dict[str, Any]


def select_financial_groups(
    pairs: Sequence[PairedGroup],
    first_keys: set[tuple[str, int, int]],
    unresolved_keys: set[tuple[str, int, int]],
    *,
    seed: int = 2110,
    fresh_misses: int = 12,
    disagreements: int = 6,
    controls: int = 4,
    per_document: int = 2,
) -> Selection:
    if min(fresh_misses, disagreements, controls, per_document) <= 0:
        raise ValueError("Positive sample sizes and cap required")
    lookup = {p.key: p for p in pairs}
    if len(lookup) != len(pairs) or not unresolved_keys <= first_keys <= set(lookup):
        raise ValueError("Invalid first-audit or unresolved grouping")
    first_docs = {k[0] for k in first_keys}
    invoice = [p for p in pairs if p.observations[0].document_type == "invoice"]
    pools = {
        "prior_unresolved": [p for p in invoice if p.key in unresolved_keys],
        "fresh_misses": [
            p
            for p in invoice
            if p.key[0] not in first_docs and not any(o.header_detected for o in p.observations)
        ],
        "ocr_disagreements": [
            p
            for p in invoice
            if p.key[0] not in first_docs
            and p.observations[0].header_detected != p.observations[1].header_detected
        ],
        "detected_controls": [
            p
            for p in invoice
            if p.key[0] not in first_docs and all(o.header_detected for o in p.observations)
        ],
    }
    requested = dict(
        zip(
            TIERS,
            (len(pools["prior_unresolved"]), fresh_misses, disagreements, controls),
            strict=True,
        )
    )
    chosen: list[PairedGroup] = []
    tiers: list[str] = []
    cap: Counter[str] = Counter()
    achieved: Counter[str] = Counter(dict.fromkeys(TIERS, 0))
    excluded: Counter[str] = Counter(dict.fromkeys(TIERS, 0))
    for tier in TIERS:
        buckets: dict[tuple[str, ...], list[PairedGroup]] = defaultdict(list)
        for pair in pools[tier]:
            buckets[pair.stratum].append(pair)
        for bucket in buckets.values():
            bucket.sort(key=lambda p: (_rank(p.key, seed), p.key))
        strata = sorted(buckets, key=lambda s: (_rank((tier, s), seed), s))
        while achieved[tier] < requested[tier]:
            progress = False
            for stratum in strata:
                bucket = buckets[stratum]
                while bucket and cap[bucket[0].key[0]] >= per_document:
                    bucket.pop(0)
                    excluded[tier] += 1
                if bucket and achieved[tier] < requested[tier]:
                    pair = bucket.pop(0)
                    chosen.append(pair)
                    tiers.append(tier)
                    cap[pair.key[0]] += 1
                    achieved[tier] += 1
                    progress = True
            if not progress:
                break
    return Selection(
        tuple(chosen),
        tuple(tiers),
        {
            "seed": seed,
            "per_document_cap": per_document,
            "requested": requested,
            "achieved": dict(achieved),
            "eligible": {t: len(pools[t]) for t in TIERS},
            "shortfall": {t: requested[t] - achieved[t] for t in TIERS},
            "cap_exclusions_encountered": dict(excluded),
            "invoice_stratum_universe": len(invoice),
            "non_invoice_stratum_exclusions": len(pairs) - len(invoice),
            "first_audit_groups_excluded_from_fresh": len(first_keys),
            "first_audit_documents_excluded_from_fresh": len(first_docs),
            "fresh_invoice_groups_excluded_by_prior_document": sum(
                p.key[0] in first_docs for p in invoice
            ),
            "selected_pairs": len(chosen),
            "selected_documents": len(cap),
        },
    )


def blind_order(selection: Selection, pass_number: int, seed: int = 2110) -> list[int]:
    if pass_number not in {1, 2}:
        raise ValueError("Two review passes only")
    return sorted(
        range(len(selection.pairs)),
        key=lambda i: _rank((pass_number, selection.pairs[i].key), seed),
    )


def blank_pass(selection: Selection, pass_number: int) -> list[dict[str, Any]]:
    # Only anonymous ordinal and mode; no selection tier, baseline stage or prior labels.
    return [
        {"slot": slot, "mode": mode, "assessment": None}
        for slot, _ in enumerate(blind_order(selection, pass_number, selection.accounting["seed"]))
        for mode in MODES
    ]


def read_pass(
    selection: Selection, pass_number: int, rows: list[dict[str, Any]]
) -> dict[tuple[int, str], Assessment]:
    order = blind_order(selection, pass_number, selection.accounting["seed"])
    result: dict[tuple[int, str], Assessment] = {}
    seen = set()
    for row in rows:
        if set(row) != {"slot", "mode", "assessment"}:
            raise ValueError("Unexpected private review keys")
        slot, mode = row["slot"], row["mode"]
        if (
            type(slot) is not int
            or slot not in range(len(order))
            or mode not in MODES
            or (slot, mode) in seen
        ):
            raise ValueError("Duplicate or unknown blind review")
        seen.add((slot, mode))
        if row["assessment"] is not None:
            result[(order[slot], mode)] = Assessment.model_validate(row["assessment"])
    if len(seen) != len(order) * 2:
        raise ValueError("Incomplete blinded review template")
    return result


def fingerprint(assessment: Assessment) -> str:
    value = assessment.model_dump(mode="json", exclude={"notes", "evidence"})
    value["amounts"] = sorted(value["amounts"])
    value["competing"] = sorted(value["competing"])
    return json.dumps(value, sort_keys=True)


def seal_pass(root: Path, selection: Selection, number: int) -> None:
    if number not in {1, 2}:
        raise ValueError("Two review passes only")
    _no_links(root / f"pass-{number}" / "reviews.json")
    _no_links(root / f"pass-{number}.seal")
    data = (root / f"pass-{number}" / "reviews.json").read_bytes()
    reviews = read_pass(selection, number, json.loads(data))
    if len(reviews) != len(selection.pairs) * 2:
        raise ValueError("Inspect every mode observation before sealing a pass")
    with (root / f"pass-{number}.seal").open("x", encoding="utf-8") as out:
        out.write(hashlib.sha256(data).hexdigest())


def verify_seal(root: Path, number: int) -> None:
    if number not in {1, 2}:
        raise ValueError("Two review passes only")
    _no_links(root / f"pass-{number}" / "reviews.json")
    _no_links(root / f"pass-{number}.seal")
    digest = hashlib.sha256((root / f"pass-{number}" / "reviews.json").read_bytes()).hexdigest()
    if digest != (root / f"pass-{number}.seal").read_text(encoding="utf-8"):
        raise ValueError("Sealed review pass was modified")


def aggregate_financial(
    selection: Selection,
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
    adjudications: list[dict[str, Any]],
    *,
    reviewer_kind: str = "same_reviewer_blinded_repeat",
    reviewer_source: str = "assistant",
) -> dict[str, Any]:
    if reviewer_kind not in REVIEW_KINDS:
        raise ValueError("Unsupported reviewer provenance")
    if reviewer_source not in {"assistant", "human_declared"} or (
        reviewer_source == "assistant" and reviewer_kind == "two_independent_reviewers"
    ):
        raise ValueError("Unsupported reviewer source or independence claim")
    a, b = read_pass(selection, 1, first), read_pass(selection, 2, second)
    final: dict[tuple[int, str], Assessment] = {}
    decisions: Counter[str] = Counter()
    for row in adjudications:
        if set(row) != {"case", "mode", "assessment", "resolution", "notes"}:
            raise ValueError("Unexpected adjudication keys")
        key = (row["case"], row["mode"])
        if (
            type(key[0]) is not int
            or key[0] not in range(len(selection.pairs))
            or key[1] not in MODES
            or key in final
        ):
            raise ValueError("Invalid or duplicate adjudication")
        if key not in a or key not in b:
            raise ValueError("Adjudication requires both inspected passes")
        adjudicated_value = Assessment.model_validate(row["assessment"])
        resolution = row["resolution"]
        same = fingerprint(a[key]) == fingerprint(b[key])
        if resolution not in {
            "confirmed_agreement",
            "resolved_disagreement",
            "retained_uncertainty",
        }:
            raise ValueError("Unsupported adjudication resolution")
        if resolution == "confirmed_agreement" and (
            not same or fingerprint(adjudicated_value) != fingerprint(a[key])
        ):
            raise ValueError("Agreement cannot conceal reviewer differences")
        if resolution == "resolved_disagreement" and (
            same or adjudicated_value.primary == Barrier.UNKNOWN
        ):
            raise ValueError("Resolved disagreement must resolve an actual difference")
        if resolution == "retained_uncertainty" and adjudicated_value.primary != Barrier.UNKNOWN:
            raise ValueError("Retained uncertainty needs an unresolved primary")
        final[key] = adjudicated_value
        decisions[resolution] += 1
    modes: dict[str, Any] = {}
    for mode in MODES:
        detected = sum(
            next(o for o in p.observations if o.mode == mode).header_detected
            for p in selection.pairs
        )
        categories = Counter(dict.fromkeys([x.value for x in Barrier], 0))
        visual = Counter(dict.fromkeys(VISUAL, 0))
        tables = Counter(dict.fromkeys(TABLES, 0))
        roles = {r: Counter(dict.fromkeys(ROLE_STATES, 0)) for r in ROLES}
        amounts = Counter(dict.fromkeys(AMOUNTS, 0))
        competing = 0
        inspected = 0
        eligible = Counter(dict.fromkeys([x.value for x in Barrier], 0))
        eligible_n = 0
        unresolved_misses = 0
        uncertain_roles = 0
        for index, pair in enumerate(selection.pairs):
            value = final.get((index, mode))
            obs = next(o for o in pair.observations if o.mode == mode)
            if not obs.header_detected and (value is None or value.primary == Barrier.UNKNOWN):
                unresolved_misses += 1
            if value is None:
                continue
            inspected += 1
            categories[value.primary] += 1
            visual[value.visual_invoice] += 1
            tables[value.table] += 1
            for role in ROLES:
                roles[role][value.roles[role]] += 1
            amounts.update(value.amounts)
            competing += bool(value.competing)
            uncertain_roles += any(s in {"unknown", "competing"} for s in value.roles.values())
            if value.visual_invoice == "yes" and not obs.header_detected:
                eligible_n += 1
                eligible[value.primary] += 1
        paired_review_keys = [
            (i, mode) for i in range(len(selection.pairs)) if (i, mode) in a and (i, mode) in b
        ]
        modes[mode] = {
            "selected_denominator": len(selection.pairs),
            "actual_header_misses": len(selection.pairs) - detected,
            "detected_headers": detected,
            "adjudicated": inspected,
            "unadjudicated": len(selection.pairs) - inspected,
            "unresolved_count": len(selection.pairs) - inspected + categories[Barrier.UNKNOWN],
            "unresolved_header_misses": unresolved_misses,
            "unknown_or_competing_role_count": uncertain_roles,
            "primary_barriers": dict(categories),
            "visual_invoice": dict(visual),
            "table_kind": dict(tables),
            "roles": {r: dict(c) for r, c in roles.items()},
            "amount_signals": dict(amounts),
            "competing_explanation_count": competing,
            "both_passes_inspected_denominator": len(paired_review_keys),
            "pass_primary_disagreement": sum(
                a[k].primary != b[k].primary for k in paired_review_keys
            ),
            "pass_any_classification_disagreement": sum(
                fingerprint(a[k]) != fingerprint(b[k]) for k in paired_review_keys
            ),
            "visually_invoice_miss_denominator": eligible_n,
            "visually_invoice_miss_barriers": dict(eligible),
        }
    paired = [
        (final[(i, MODES[0])], final[(i, MODES[1])])
        for i in range(len(selection.pairs))
        if all((i, m) in final for m in MODES)
    ]
    transitions = Counter(
        f"{int(p.observations[0].header_detected)}->{int(p.observations[1].header_detected)}"
        for p in selection.pairs
    )
    # A conservative, predeclared gate; correlated OCR modes must agree on a majority category.
    dominant: list[str] = []
    for mode in MODES:
        values = modes[mode]
        n = values["visually_invoice_miss_denominator"]
        candidates = [
            c
            for c, count in values["visually_invoice_miss_barriers"].items()
            if count >= 8
            and count * 2 > n
            and c not in {Barrier.UNKNOWN, Barrier.CLEAR, Barrier.SCOPE}
        ]
        dominant.append(candidates[0] if candidates else "unresolved")
    complete = len(final) == 2 * len(selection.pairs) and bool(final)
    choice = dominant[0] if complete and dominant[0] == dominant[1] else "unresolved"
    if choice in {Barrier.LABELS, Barrier.GEOMETRY}:
        # Category majority alone does not verify one repeated explicit pattern.
        choice = "unresolved"
    return {
        "scope": SCOPE,
        "sample_method": METHOD,
        "reviewer_kind": reviewer_kind,
        "reviewer_source": reviewer_source,
        "selection": selection.accounting,
        "modes": modes,
        "adjudication_resolution_counts": dict(decisions),
        "jointly_adjudicated_pair_denominator": len(paired),
        "paired_primary_changes": sum(x.primary != y.primary for x, y in paired),
        "paired_role_changes": {r: sum(x.roles[r] != y.roles[r] for x, y in paired) for r in ROLES},
        "header_transitions": dict(transitions),
        "decision_matrix": DECISION_MATRIX,
        "decision_gate": (
            "complete adjudication; at least eight and strict majority of visually confirmed "
            "invoice misses in each mode; modes agree; layout/label pattern still needs "
            "explicit repetition evidence"
        ),
        "next_choice": choice,
        "next_implementation": DECISION_MATRIX[choice],
        "limitations": [
            "DocILE invoice stratum is not visual invoice confirmation.",
            "Nonrepresentative, equal-stratum qualitative selection; observed development data.",
            "Same-reviewer repeat is not independent inter-rater reliability.",
            "Assistant repeat review does not establish independent human adjudication.",
            "No arithmetic or annotation-only inference of financial roles.",
            "Correlated OCR modes and groups are not independent observations.",
            "Printed-role judgments concern page/table context, not annotation-row field accuracy.",
            "Source familiarity and memory can survive label blinding.",
            "Category majority does not establish a repeated explicit parser pattern.",
            "Unadjudicated and unknown evidence is unresolved, not a confirmed cause.",
        ],
    }


def validate_public(report: dict[str, Any]) -> None:
    empty = Selection(
        (),
        (),
        {
            "seed": 2110,
            "per_document_cap": 2,
            "requested": dict.fromkeys(TIERS, 0),
            "achieved": dict.fromkeys(TIERS, 0),
            "eligible": dict.fromkeys(TIERS, 0),
            "shortfall": dict.fromkeys(TIERS, 0),
            "cap_exclusions_encountered": dict.fromkeys(TIERS, 0),
            "invoice_stratum_universe": 0,
            "non_invoice_stratum_exclusions": 0,
            "first_audit_groups_excluded_from_fresh": 0,
            "first_audit_documents_excluded_from_fresh": 0,
            "fresh_invoice_groups_excluded_by_prior_document": 0,
            "selected_pairs": 0,
            "selected_documents": 0,
        },
    )
    template = aggregate_financial(empty, [], [], [])

    def strings(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(strings(v) for v in value.values()), set())
        if isinstance(value, list):
            return set().union(*(strings(v) for v in value), set())
        return {value} if isinstance(value, str) else set()

    allowed = (
        strings(template)
        | set(REVIEW_KINDS)
        | {"assistant", "human_declared"}
        | set(TIERS)
        | {
            "0->0",
            "0->1",
            "1->0",
            "1->1",
            "confirmed_agreement",
            "resolved_disagreement",
            "retained_uncertainty",
        }
    )
    if not strings(report) <= allowed:
        raise ValueError("Non-allowlisted public string or key")

    def shape(value: Any, expected: Any) -> None:
        if isinstance(expected, dict):
            if not isinstance(value, dict) or set(value) != set(expected):
                raise ValueError("Public aggregate schema mismatch")
            for k in expected:
                shape(value[k], expected[k])
        elif isinstance(expected, int):
            if type(value) is not int or value < 0:
                raise ValueError("Aggregate counts must be nonnegative integers")
        elif isinstance(expected, str):
            if not isinstance(value, str):
                raise ValueError("Public string schema mismatch")
        elif isinstance(expected, list) and value != expected:
            raise ValueError("Public fixed-list schema mismatch")

    # These two counters have dynamic, allowlisted keys; everything else has a fixed shape.
    normalized = dict(report)
    dynamic_keys = {
        "header_transitions": {"0->0", "0->1", "1->0", "1->1"},
        "adjudication_resolution_counts": {
            "confirmed_agreement",
            "resolved_disagreement",
            "retained_uncertainty",
        },
    }
    for k, keys in dynamic_keys.items():
        if (
            not isinstance(report[k], dict)
            or any(type(v) is not int or v < 0 for v in report[k].values())
            or not set(report[k]) <= keys
        ):
            raise ValueError("Aggregate counters must be nonnegative integers")
        normalized[k] = {}
    shape(normalized, template)
    for key in ("scope", "sample_method", "decision_matrix", "decision_gate", "limitations"):
        if report[key] != template[key]:
            raise ValueError("Public prose must be fixed")
    n = report["selection"]["selected_pairs"]
    if sum(report["selection"]["achieved"].values()) != n:
        raise ValueError("Selection denominator mismatch")
    if sum(report["header_transitions"].values()) != n or sum(
        report["adjudication_resolution_counts"].values()
    ) != sum(v["adjudicated"] for v in report["modes"].values()):
        raise ValueError("Paired or adjudication denominator mismatch")
    for mode in MODES:
        v = report["modes"][mode]
        if (
            v["selected_denominator"] != n
            or v["actual_header_misses"] + v["detected_headers"] != n
            or v["adjudicated"] + v["unadjudicated"] != n
            or sum(v["primary_barriers"].values()) != v["adjudicated"]
            or v["unresolved_count"] != v["unadjudicated"] + v["primary_barriers"]["unresolved"]
            or v["unresolved_header_misses"] > v["actual_header_misses"]
            or v["pass_primary_disagreement"] > v["pass_any_classification_disagreement"]
            or v["pass_any_classification_disagreement"] > v["both_passes_inspected_denominator"]
            or sum(v["visually_invoice_miss_barriers"].values())
            != v["visually_invoice_miss_denominator"]
        ):
            raise ValueError("Mode denominator mismatch")
        for counts in [v["visual_invoice"], v["table_kind"], *v["roles"].values()]:
            if sum(counts.values()) != v["adjudicated"]:
                raise ValueError("Classification denominator mismatch")


def write_public(path: Path, report: dict[str, Any]) -> None:
    validate_public(report)
    for name in ("report.json", "report.md"):
        _no_links(path / name)
        if (path / name).exists():
            raise FileExistsError("Aggregate reports must be fresh")
    with (path / "report.json").open("x", encoding="utf-8") as out:
        json.dump(report, out, indent=2, sort_keys=True)
        out.write("\n")
    with (path / "report.md").open("x", encoding="utf-8") as out:
        out.write("# Invoice-focused financial-role adjudication\n\n")
        out.write(
            f"{SCOPE}.\n\nReview provenance: **{report['reviewer_kind']}**, "
            f"source **{report['reviewer_source']}**.\n\n"
        )
        out.write(
            "Same-reviewer repeat is not independent inter-rater reliability; "
            "label blinding cannot erase source familiarity.\n\n"
        )
        s = report["selection"]
        out.write(
            f"Fixed seed **{s['seed']}**; {METHOD}. **{s['selected_pairs']} pairs from "
            f"{s['selected_documents']} documents**, capped at {s['per_document_cap']} "
            "groups per document across all tiers; the same groups are reviewed in both modes.\n\n"
        )
        out.write(
            "| Selection tier | Requested | Achieved | Eligible | Shortfall | Cap exclusions "
            "encountered |\n|---|---:|---:|---:|---:|---:|\n"
        )
        for tier in TIERS:
            out.write(
                f"| {tier} | "
                + " | ".join(
                    str(s[k][tier])
                    for k in (
                        "requested",
                        "achieved",
                        "eligible",
                        "shortfall",
                        "cap_exclusions_encountered",
                    )
                )
                + " |\n"
            )
        out.write(
            f"\nInvoice-stratum universe: {s['invoice_stratum_universe']} groups; "
            f"{s['non_invoice_stratum_exclusions']} other-stratum groups excluded. Fresh tiers "
            f"exclude all {s['first_audit_groups_excluded_from_fresh']} first-audit groups and "
            f"their {s['first_audit_documents_excluded_from_fresh']} documents "
            f"({s['fresh_invoice_groups_excluded_by_prior_document']} invoice-stratum groups). "
            "Cap exclusions count candidates encountered, not an exhaustive excluded population. "
            "The first 48-pair audit and all frozen line-coverage reports are unchanged.\n\n"
        )
        out.write(
            "| Mode | Selected | Header misses | Adjudicated | Unresolved | "
            "Primary / any pass disagreements, each / both inspected "
            "|\n|---|---:|---:|---:|---:|---|\n"
        )
        for mode in MODES:
            v = report["modes"][mode]
            out.write(
                f"| {mode} | {v['selected_denominator']} | "
                f"{v['actual_header_misses']} | {v['adjudicated']} | "
                f"{v['unresolved_count']} | "
                f"{v['pass_primary_disagreement']}/{v['both_passes_inspected_denominator']} / "
                f"{v['pass_any_classification_disagreement']}/"
                f"{v['both_passes_inspected_denominator']} |\n"
            )
        out.write(
            "\nUnresolved among actual header misses: "
            + "; ".join(
                f"**{m}: {report['modes'][m]['unresolved_header_misses']}/"
                f"{report['modes'][m]['actual_header_misses']}**"
                for m in MODES
            )
            + ". Unresolved primary evidence is separate from "
            "unknown/competing financial roles.\n\n"
        )
        out.write(
            "DocILE invoice stratum is not visual confirmation.\n\n"
            "| Mode | Visually invoice | Not invoice | Unknown | Genuine item table | "
            "Summary | List | None | Unknown table | Denominator |\n"
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        )
        for m in MODES:
            v = report["modes"][m]
            counts = [
                *(v["visual_invoice"][k] for k in VISUAL),
                *(v["table_kind"][k] for k in TABLES),
                v["adjudicated"],
            ]
            out.write(f"| {m} | " + " | ".join(map(str, counts)) + " |\n")
        out.write(
            "\n| Mode | Primary barrier | Count | Adjudicated denominator |\n|---|---|---:|---:|\n"
        )
        for mode in MODES:
            v = report["modes"][mode]
            for category in Barrier:
                count = v["primary_barriers"][category]
                out.write(f"| {mode} | {category} | {count} | {v['adjudicated']} |\n")
        out.write(
            "\nThe decision gate uses **visually confirmed invoice misses**, excluding "
            "detected controls and unconfirmed document types.\n\n"
            "| Mode | Primary barrier | Count | Invoice-miss denominator |\n"
            "|---|---|---:|---:|\n"
        )
        for m in MODES:
            v = report["modes"][m]
            for c in Barrier:
                count = v["visually_invoice_miss_barriers"][c]
                if count:
                    out.write(
                        f"| {m} | {c} | {count} | {v['visually_invoice_miss_denominator']} |\n"
                    )
        out.write(
            "\n| Mode | Printed role | Present | Absent | Unknown | Competing | "
            "Denominator |\n|---|---|---:|---:|---:|---:|---:|\n"
        )
        for m in MODES:
            v = report["modes"][m]
            for role in ROLES:
                states = v["roles"][role]
                out.write(
                    f"| {m} | {role} | "
                    + " | ".join(str(states[s]) for s in ROLE_STATES)
                    + f" | {v['adjudicated']} |\n"
                )
        out.write(
            "\n| Mode | Amount context signal | Count | Adjudicated denominator |\n"
            "|---|---|---:|---:|\n"
        )
        for m in MODES:
            v = report["modes"][m]
            for signal in AMOUNTS:
                count = v["amount_signals"][signal]
                out.write(f"| {m} | {signal} | {count} | {v['adjudicated']} |\n")
        out.write(
            "\nAmount signals are multilabel; their counts do not sum to the denominator. "
            "They identify printed context, not inferred monetary values.\n\n"
        )
        for m in MODES:
            v = report["modes"][m]
            out.write(
                f"{m}: unknown/competing financial role in "
                f"{v['unknown_or_competing_role_count']}/{v['adjudicated']}; "
                f"competing primary explanations in "
                f"{v['competing_explanation_count']}/{v['adjudicated']}.\n\n"
            )
        out.write(
            f"\nPaired primary changes: "
            f"{report['paired_primary_changes']}/{report['jointly_adjudicated_pair_denominator']}.\n\n"
        )
        out.write(
            "Header detection transitions (end-to-end -> precomputed; 0=miss, 1=detected): "
            + "; ".join(
                f"{k}: {v}/{s['selected_pairs']}"
                for k, v in sorted(report["header_transitions"].items())
            )
            + ".\n\n"
        )
        out.write(
            "Paired printed-role classification changes: "
            + "; ".join(
                f"{r}: {v}/{report['jointly_adjudicated_pair_denominator']}"
                for r, v in ((r, report["paired_role_changes"][r]) for r in ROLES)
            )
            + ".\n\n"
        )
        total = sum(report["adjudication_resolution_counts"].values())
        out.write(
            "Explicit adjudication: "
            + "; ".join(
                f"{k}: {v}/{total}"
                for k, v in sorted(report["adjudication_resolution_counts"].items())
            )
            + ".\n\n"
        )
        out.write("| Supported dominant category | Potential next implementation |\n|---|---|\n")
        for decision_category, implementation in DECISION_MATRIX.items():
            out.write(f"| {decision_category} | {implementation} |\n")
        out.write(
            f"\nGate: {report['decision_gate']}.\n\n**Choice: "
            f"{report['next_implementation']}.**\n\n"
        )
        for limitation in report["limitations"]:
            out.write(f"- {limitation}\n")
        out.write(
            "\nNo extractor or official metric changes; this is not a coverage gain. "
            "The host Tesseract smoke limitation is not a commit blocker: actual audit "
            "OCR preparation ran in the guarded evaluator container.\n"
        )
