"""Evaluation-only paired sampling and reviewed explanations; no extraction behavior."""

import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from invoiceops.evaluation.line_coverage import LineCoverageTrace, _word_in_field

MODES = ("end_to_end", "precomputed_ocr")
SIGNATURES = (
    "none",
    "description_only",
    "description_line_total",
    "description_unit_price",
    "other_known_combination",
    "mixed",
)


class Explanation(StrEnum):
    TOKENS_ABSENT = "tokens_absent"
    WORDING = "wording_not_supported"
    GEOMETRY = "geometry_or_row_grouping"
    CONTINUATION = "continuation_page"
    NOT_INVOICE = "document_not_invoice"
    COORDINATES = "annotation_or_coordinate_mismatch"
    UNCERTAIN = "other_or_uncertain"
    DETECTED = "detected_header_verified"


@dataclass(frozen=True, repr=False)
class Observation:
    document_id: str
    page: int
    line_item_id: int
    mode: str
    document_type: str
    page_position: str
    header_detected: bool
    token_present: bool
    signature: str
    earlier_page_has_header: bool = False
    prior_page_has_lir: bool = False
    same_line_id_on_other_page: bool = False
    overlap_without_center_fields: int = 0
    invalid_box_fields: int = 0
    field_count: int = 0

    @property
    def key(self) -> tuple[str, int, int]:
        return self.document_id, self.page, self.line_item_id


@dataclass(frozen=True, repr=False)
class PairedGroup:
    observations: tuple[Observation, Observation]

    @property
    def key(self) -> tuple[str, int, int]:
        return self.observations[0].key

    @property
    def stratum(self) -> tuple[str, ...]:
        first = self.observations[0]
        return (first.document_type, first.page_position) + tuple(
            f"{o.mode}:{int(o.header_detected)}:{int(o.token_present)}:{o.signature}"
            for o in self.observations
        )


def normalized_box(field: Any, page_count: int) -> bool:
    values = (field.bbox.left, field.bbox.top, field.bbox.right, field.bbox.bottom)
    return (
        isinstance(field.page, int)
        and 0 <= field.page < page_count
        and all(math.isfinite(v) and 0 <= v <= 1 for v in values)
        and values[0] < values[2]
        and values[1] < values[3]
    )


def grouped_fields(fields: Sequence[Any]) -> dict[tuple[int, int], list[Any]]:
    """Keep page-local groups; missing IDs are explicitly excluded, never merged."""
    groups: dict[tuple[int, int], list[Any]] = defaultdict(list)
    for field in fields:
        if field.line_item_id is not None:
            groups[(field.page, field.line_item_id)].append(field)
    return dict(groups)


def _overlaps(word: Any, field: Any) -> bool:
    return bool(
        word.page == field.page
        and min(word.bbox.x1, field.bbox.right) > max(word.bbox.x0, field.bbox.left)
        and min(word.bbox.y1, field.bbox.bottom) > max(word.bbox.y0, field.bbox.top)
    )


def observe_groups(
    document_id: str,
    document_type: str,
    mode: str,
    trace: LineCoverageTrace,
    fields: Sequence[Any],
    page_count: int,
) -> list[Observation]:
    """Observable signals only. Earlier headers do not establish continuation."""
    from invoiceops.extraction.table_layout import LineItemColumn, _best_anchor, detect_table_header

    if mode not in MODES:
        raise ValueError("Unsupported OCR mode")
    kind = (
        "invoice"
        if document_type.lower() in {"invoice", "tax_invoice", "tax invoice"}
        else ("unknown" if not document_type or document_type.lower() == "unknown" else "other")
    )
    groups = grouped_fields(fields)
    pages = {page for page, _ in groups}
    line_pages: dict[int, set[int]] = defaultdict(set)
    words_by_page: dict[int, list[Any]] = defaultdict(list)
    signatures_by_page: dict[int, set[str]] = defaultdict(set)
    for page, line in groups:
        line_pages[line].add(page)
    for row in trace.rows:
        words_by_page[row.page].extend(row.words)
        if detect_table_header(row) is None and not any(
            char.isdigit() for word in row.words for char in word.text
        ):
            columns = {c.value for c in LineItemColumn if _best_anchor(row, c) is not None}
            if "description" in columns:
                label = {
                    frozenset({"description"}): "description_only",
                    frozenset({"description", "line_total"}): "description_line_total",
                    frozenset({"description", "unit_price"}): "description_unit_price",
                }.get(frozenset(columns), "other_known_combination")
                signatures_by_page[row.page].add(label)
    observations = []
    for (page, line), group in sorted(groups.items()):
        valid = [field for field in group if normalized_box(field, page_count)]
        words = words_by_page[page]
        contained = [any(_word_in_field(word, field) for word in words) for field in valid]
        overlap_only = sum(
            not center and any(_overlaps(word, field) for word in words)
            for field, center in zip(valid, contained, strict=True)
        )
        signatures = signatures_by_page[page]
        signature = (
            "none"
            if not signatures
            else (next(iter(signatures)) if len(signatures) == 1 else "mixed")
        )
        observations.append(
            Observation(
                document_id,
                page,
                line,
                mode,
                kind,
                "first" if page == 0 else "later",
                page in trace.page_has_header,
                any(contained),
                signature,
                any(previous < page for previous in trace.page_has_header),
                any(previous < page for previous in pages),
                len(line_pages[line]) > 1,
                overlap_only,
                len(group) - len(valid),
                len(group),
            )
        )
    return observations


def pair_groups(observations: Sequence[Observation]) -> list[PairedGroup]:
    groups: dict[tuple[str, int, int], dict[str, Observation]] = defaultdict(dict)
    for observation in observations:
        if observation.mode not in MODES or observation.mode in groups[observation.key]:
            raise ValueError("Unsupported or duplicate mode observation")
        if observation.document_type not in {"invoice", "other", "unknown"}:
            raise ValueError("Unsafe document-type label")
        if observation.page_position not in {"first", "later"}:
            raise ValueError("Unsafe page-position label")
        if observation.signature not in SIGNATURES:
            raise ValueError("Unsafe signature label")
        groups[observation.key][observation.mode] = observation
    pairs = []
    for key in sorted(groups):
        if set(groups[key]) != set(MODES):
            raise ValueError("Every selected group must be paired across both modes")
        a, b = (groups[key][mode] for mode in MODES)
        if (a.document_type, a.page_position) != (b.document_type, b.page_position):
            raise ValueError("Paired annotation metadata differs")
        pairs.append(PairedGroup((a, b)))
    return pairs


def _rank(value: object, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()


def select_groups(
    pairs: Sequence[PairedGroup],
    *,
    misses: int = 40,
    controls: int = 8,
    seed: int = 1205,
    per_document: int = 2,
) -> list[PairedGroup]:
    """Seed-ranked round-robin joint strata; controls reserve capacity first."""
    if min(misses, controls, per_document) <= 0:
        raise ValueError("Sample sizes and document cap must be positive")
    if len({pair.key for pair in pairs}) != len(pairs):
        raise ValueError("Duplicate paired group")
    selected = []
    document_counts: Counter[str] = Counter()
    for detected, target in ((True, controls), (False, misses)):
        buckets: dict[tuple[str, ...], list[PairedGroup]] = defaultdict(list)
        for pair in pairs:
            if all(o.header_detected for o in pair.observations) == detected:
                buckets[pair.stratum].append(pair)
        strata = sorted(buckets, key=lambda s: (_rank(s, seed), s))
        for bucket in buckets.values():
            bucket.sort(key=lambda pair: (_rank(pair.key, seed), pair.key))
        count = 0
        while count < target:
            progress = False
            for stratum in strata:
                bucket = buckets[stratum]
                while bucket and document_counts[bucket[0].key[0]] >= per_document:
                    bucket.pop(0)
                if bucket and count < target:
                    pair = bucket.pop(0)
                    selected.append(pair)
                    document_counts[pair.key[0]] += 1
                    count += 1
                    progress = True
            if not progress:
                break
    return selected


REQUIRED_EVIDENCE = {
    Explanation.TOKENS_ABSENT: {"source_page_inspected", "tokens_inspected", "visible_text_absent"},
    Explanation.WORDING: {
        "source_page_inspected",
        "tokens_inspected",
        "header_visible",
        "aliases_checked",
    },
    Explanation.GEOMETRY: {
        "source_page_inspected",
        "tokens_inspected",
        "header_visible",
        "row_geometry_checked",
    },
    Explanation.CONTINUATION: {
        "source_page_inspected",
        "tokens_inspected",
        "prior_page_inspected",
        "continued_table_verified",
        "no_repeated_header_verified",
    },
    Explanation.NOT_INVOICE: {"source_page_inspected", "tokens_inspected", "document_type_checked"},
    Explanation.COORDINATES: {
        "source_page_inspected",
        "tokens_inspected",
        "annotations_inspected",
        "grouping_checked",
        "coordinate_mismatch_verified",
    },
    Explanation.UNCERTAIN: {"source_page_inspected", "tokens_inspected"},
    Explanation.DETECTED: {
        "source_page_inspected",
        "tokens_inspected",
        "header_visible",
        "detected_row_verified",
    },
}


def review_template(selected: Sequence[PairedGroup]) -> list[dict[str, Any]]:
    return [
        {"case": index, "mode": mode, "primary": None, "evidence": [], "notes": ""}
        for index, _ in enumerate(selected)
        for mode in MODES
    ]


def aggregate_audit(
    pairs: Sequence[PairedGroup],
    selected: Sequence[PairedGroup],
    reviews: list[dict[str, Any]],
    *,
    seed: int = 1205,
    per_document: int = 2,
    requested_misses: int = 40,
    requested_controls: int = 8,
) -> dict[str, Any]:
    """Allowlist export. Private notes, keys, paths and case-level rows are never returned."""
    if len({p.key for p in selected}) != len(selected):
        raise ValueError("Duplicate selected group")
    universe_keys = {p.key for p in pairs}
    if any(p.key not in universe_keys for p in selected):
        raise ValueError("Selection is outside the paired universe")
    if max(Counter(p.key[0] for p in selected).values(), default=0) > per_document:
        raise ValueError("Document cap violated")
    indexed: dict[tuple[int, str], dict[str, Any]] = {}
    for review in reviews:
        key = (review["case"], review["mode"])
        if key in indexed or key[0] not in range(len(selected)) or key[1] not in MODES:
            raise ValueError("Duplicate or unknown private review")
        indexed[key] = review
    mode_reports = {}
    labels: dict[tuple[int, str], str] = {}
    for mode in MODES:
        categories: Counter[str] = Counter({e.value: 0 for e in Explanation})
        signals: Counter[str] = Counter()
        strata: dict[str, Counter[str]] = {
            k: Counter()
            for k in (
                "document_type",
                "page_position",
                "token_presence",
                "header_signature",
                "header_detection",
            )
        }
        by_type: dict[str, Counter[str]] = defaultdict(Counter)
        inspected = 0
        for index, pair in enumerate(selected):
            observation = next(o for o in pair.observations if o.mode == mode)
            review = indexed.get((index, mode), {})
            primary = review.get("primary")
            if primary is None:
                label = "unreviewed"
            else:
                explanation = Explanation(primary)
                evidence = set(review.get("evidence", []))
                if not REQUIRED_EVIDENCE[explanation] <= evidence:
                    raise ValueError("Explanation lacks required inspection evidence")
                if explanation == Explanation.DETECTED and not observation.header_detected:
                    raise ValueError("An undetected header cannot be a verified detected control")
                label = explanation.value
                inspected += 1
                categories[label] += 1
            labels[(index, mode)] = label
            by_type[observation.document_type][label] += 1
            signals.update(
                {
                    "earlier_page_has_header": int(observation.earlier_page_has_header),
                    "prior_page_has_lir": int(observation.prior_page_has_lir),
                    "same_line_id_on_other_page": int(observation.same_line_id_on_other_page),
                    "groups_with_overlap_without_center": int(
                        observation.overlap_without_center_fields > 0
                    ),
                    "groups_with_invalid_boxes": int(observation.invalid_box_fields > 0),
                }
            )
            strata["document_type"][observation.document_type] += 1
            strata["page_position"][observation.page_position] += 1
            strata["token_presence"]["present" if observation.token_present else "absent"] += 1
            strata["header_signature"][observation.signature] += 1
            strata["header_detection"][
                "detected" if observation.header_detected else "not_detected"
            ] += 1
        unreviewed = len(selected) - inspected
        mode_reports[mode] = {
            "selected_group_denominator": len(selected),
            "inspected": inspected,
            "unreviewed": unreviewed,
            "primary_explanations": dict(categories),
            "review_by_document_type": {k: dict(v) for k, v in by_type.items()},
            "uncertainty_count": unreviewed + categories[Explanation.UNCERTAIN],
            "observable_signals": dict(signals),
            "selected_strata": {k: dict(v) for k, v in strata.items()},
        }
    transitions: Counter[str] = Counter()
    disagreements: Counter[str] = Counter()
    jointly_reviewed = 0
    for index, pair in enumerate(selected):
        a, b = pair.observations
        transitions[f"{int(a.header_detected)}->{int(b.header_detected)}"] += 1
        disagreements["header_detection"] += int(a.header_detected != b.header_detected)
        disagreements["token_presence"] += int(a.token_present != b.token_present)
        disagreements["signature"] += int(a.signature != b.signature)
        left, right = (labels[(index, mode)] for mode in MODES)
        if "unreviewed" not in (left, right):
            jointly_reviewed += 1
            disagreements["review_primary"] += int(left != right)
    return {
        "scope": (
            "500-document observed development validation split; qualitative audit, not holdout"
        ),
        "sample_method": (
            "seed-ranked round-robin joint mode/type/page/token/signature strata; controls first"
        ),
        "seed": seed,
        "per_document_cap": per_document,
        "requested_misses": requested_misses,
        "requested_controls": requested_controls,
        "universe_documents_with_lir": len({p.key[0] for p in pairs}),
        "universe_paired_groups": len(pairs),
        "universe_header_miss_pairs": sum(
            not all(o.header_detected for o in p.observations) for p in pairs
        ),
        "universe_both_detected_pairs": sum(
            all(o.header_detected for o in p.observations) for p in pairs
        ),
        "selected_pairs": len(selected),
        "selected_documents": len({p.key[0] for p in selected}),
        "selected_miss_pairs": sum(
            not all(o.header_detected for o in p.observations) for p in selected
        ),
        "selected_control_pairs": sum(
            all(o.header_detected for o in p.observations) for p in selected
        ),
        "available_joint_strata": len({p.stratum for p in pairs}),
        "selected_joint_strata": len({p.stratum for p in selected}),
        "modes": mode_reports,
        "paired_denominator": len(selected),
        "jointly_reviewed_pair_denominator": jointly_reviewed,
        "header_transitions_end_to_end_to_precomputed": dict(transitions),
        "paired_disagreements": dict(disagreements),
        "limitations": [
            "Equal-stratum qualitative sampling is not proportional or representative.",
            "Header absence on a page is an observation, not a root cause.",
            "Earlier headers and cross-page IDs do not automatically establish continuation.",
            "Token-center containment is not official DocILE PCC scoring.",
            "One private reviewer; no independent adjudication or causal generalization.",
            "Uninspected and uncertain observations are not confirmed causes.",
        ],
    }


def _no_links(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink() or component.is_junction():
            raise ValueError("Output paths must not traverse links")


def private_output(path: Path, repository: Path, *, fresh: bool) -> Path:
    """Only ignored repo scratch, or the existing guarded dedicated tmpfs."""
    _no_links(path.absolute())
    resolved = path.resolve()
    repository = repository.resolve()
    scratch = repository / "work" / "docile-header-audit-private"
    if resolved.is_relative_to(scratch) and resolved != scratch:
        relative = resolved.relative_to(repository).as_posix()
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", relative],
            cwd=repository,
            check=False,
            capture_output=True,
        )
        tracked = subprocess.check_output(
            ["git", "ls-files", "--", relative],
            cwd=repository,
            text=True,
        )
        if ignored.returncode != 0 or tracked.strip():
            raise ValueError("Private output must be ignored and untracked")
    else:
        from scripts.analyze_docile_line_coverage import private_cache_root

        try:
            root = private_cache_root()
        except RuntimeError:
            raise ValueError("Use guarded private scratch or dedicated tmpfs") from None
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError("Use guarded private scratch or dedicated tmpfs")
    if fresh:
        resolved.mkdir(parents=True, exist_ok=False)
    elif not resolved.is_dir():
        raise ValueError("Private audit directory does not exist")
    return resolved


def aggregate_output(path: Path, repository: Path) -> Path:
    _no_links(path.absolute())
    resolved = path.resolve()
    root = repository.resolve() / "evals" / "reports" / "docile"
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Aggregate output must be a fresh DocILE report directory")
    resolved.mkdir(parents=True, exist_ok=False)
    return resolved


def _public_values(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(k) for k in value} | set().union(
            *(_public_values(item) for item in value.values()), set()
        )
    if isinstance(value, list):
        return set().union(*(_public_values(item) for item in value), set())
    return {value} if isinstance(value, str) else set()


def validate_aggregate(report: dict[str, Any]) -> None:
    """Reject free-form strings or case-level keys even if an export caller is mistaken."""
    template = aggregate_audit([], [], [])
    allowed = (
        _public_values(template)
        | set(SIGNATURES)
        | {
            "unreviewed",
            "invoice",
            "other",
            "unknown",
            "first",
            "later",
            "present",
            "absent",
            "detected",
            "not_detected",
            "earlier_page_has_header",
            "prior_page_has_lir",
            "same_line_id_on_other_page",
            "groups_with_overlap_without_center",
            "groups_with_invalid_boxes",
            "header_detection",
            "token_presence",
            "signature",
            "review_primary",
            "0->0",
            "0->1",
            "1->0",
            "1->1",
            "scanned_document_denominator",
            "annotation_fields_missing_line_item_id",
        }
    )
    if not _public_values(report) <= allowed:
        raise ValueError("Aggregate export contains a non-allowlisted string or key")
    for key in ("scope", "sample_method", "limitations"):
        if report.get(key) != template[key]:
            raise ValueError("Aggregate prose must be fixed, never private reviewer notes")
    for mode in MODES:
        values = report["modes"][mode]
        detection = values["selected_strata"]["header_detection"]
        if sum(detection.values()) != values["selected_group_denominator"]:
            raise ValueError("Per-mode header denominators do not reconcile")
        transitions = report["header_transitions_end_to_end_to_precomputed"]
        miss_keys = ("0->0", "0->1") if mode == "end_to_end" else ("0->0", "1->0")
        if sum(transitions.get(key, 0) for key in miss_keys) != detection.get("not_detected", 0):
            raise ValueError("Per-mode misses do not reconcile with paired transitions")
        if sum(values["primary_explanations"].values()) != values["inspected"]:
            raise ValueError("Reviewed categories do not reconcile")
        if values["inspected"] + values["unreviewed"] != values["selected_group_denominator"]:
            raise ValueError("Reviewed denominator does not reconcile")


def write_aggregate(path: Path, report: dict[str, Any]) -> None:
    """Only call with the allowlist-built aggregate report."""
    validate_aggregate(report)
    with (path / "report.json").open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    with (path / "report.md").open("x", encoding="utf-8") as output:
        output.write(render_markdown(report))


def render_markdown(report: dict[str, Any]) -> str:
    """Present paired sampling separately from each mode's actual misses."""
    from io import StringIO

    validate_aggregate(report)
    output = StringIO()
    output.write("# Qualitative paired DocILE header-miss audit\n\n")
    output.write(
        "Observed development data; no independent holdout or causal accuracy claim.\n\n"
        "**The equal-stratum sample is nonrepresentative and was reviewed by one person.**\n\n"
    )
    output.write(
        f"**The {report['selected_miss_pairs']} miss pairs mean at least one mode missed**, "
        "not that both modes missed. "
        f"{report['header_transitions_end_to_end_to_precomputed'].get('1->0', 0)} pairs "
        "were detected end-to-end but missed in precomputed OCR; "
        f"{report['header_transitions_end_to_end_to_precomputed'].get('0->1', 0)} "
        "were detected in precomputed OCR but missed end-to-end.\n\n"
    )
    output.write(
        "| Mode | Selected groups | Detected headers | Actual header misses | "
        "Uncertainty among actual misses |\n"
        "|---|---:|---:|---:|---|\n"
    )
    for mode in MODES:
        values = report["modes"][mode]
        detection = values["selected_strata"]["header_detection"]
        detected = detection.get("detected", 0)
        misses = detection.get("not_detected", 0)
        # Aggregate labels establish this subset only when every detected row is verified.
        uncertainty = (
            f"{values['uncertainty_count']}/{misses}"
            if values["primary_explanations"][Explanation.DETECTED] == detected
            else "Not derivable from aggregate labels"
        )
        output.write(
            f"| {mode} | {values['selected_group_denominator']} | {detected} | "
            f"{misses} | {uncertainty} |\n"
        )
    output.write(
        "\nThe category table below uses all selected groups; its /48 denominator "
        "is not the denominator for uncertainty among header misses.\n\n"
        if report["selected_pairs"] == 48
        else "\nThe category table below uses all selected groups, not only header misses.\n\n"
    )
    for key in (
        "seed",
        "universe_paired_groups",
        "selected_pairs",
        "selected_documents",
        "selected_miss_pairs",
        "selected_control_pairs",
        "jointly_reviewed_pair_denominator",
    ):
        output.write(f"- {key}: {report[key]}\n")
    output.write("\n| Mode | Category | Count | Selected denominator |\n|---|---|---:|---:|\n")
    for mode, values in report["modes"].items():
        for category, count in values["primary_explanations"].items():
            output.write(
                f"| {mode} | {category} | {count} | {values['selected_group_denominator']} |\n"
            )
        for category in ("inspected", "unreviewed", "uncertainty_count"):
            output.write(
                f"| {mode} | {category} | {values[category]} | "
                f"{values['selected_group_denominator']} |\n"
            )
    output.write("\nAggregate strata, paired comparisons and limitations are in report.json.\n")
    return output.getvalue()
