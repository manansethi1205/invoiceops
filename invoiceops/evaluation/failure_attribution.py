"""Private, observational first-stage attribution; no production rule changes."""

import json
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from pydantic import Field

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.human_annotations import HumanField, HumanInvoiceAnnotation
from invoiceops.evaluation.line_coverage import trace_line_parser
from invoiceops.evaluation.matching import LINE_FIELDS, align_line_items, is_exact_line_item
from invoiceops.evaluation.metrics import HEADER_FIELDS
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.real_input import (
    Aggregate,
    ObservedTextExtractor,
    fresh_public,
    member,
    private_path,
    quiet_extraction,
    source_state,
)
from invoiceops.evaluation.runner import EvaluationRunner, _length_delimited_hash
from invoiceops.extraction import header_rules
from invoiceops.extraction.candidates import resolve_candidates
from invoiceops.extraction.layout import reconstruct_lines
from invoiceops.extraction.normalization import (
    normalize_currency,
    parse_invoice_date,
    parse_money,
)
from invoiceops.extraction.ocr_runtime import inspect_ocr_runtime
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.schemas.extraction import (
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    WordToken,
)

type Category = Literal[
    "correct",
    "correct_absence",
    "excluded_unannotated",
    "extraction_failed",
    "tokens_not_observed",
    "annotation_or_tokens_unresolved",
    "region_not_detected",
    "candidate_not_emitted",
    "ambiguous_candidate",
    "wrong_role",
    "wrong_row",
    "wrong_value",
    "scorer_only",
    "evidence_unresolved",
    "false_on_absent",
    "absence_unscorable",
]
type Family = Literal[
    "net_tax_gross_token_signature",
    "other_detected_table",
    "no_detected_table_header",
    "unscorable",
]
type RowCategory = Literal[
    "exact",
    "scorer_only",
    "no_detected_header",
    "detected_no_associated_row",
    "wrong_row_values",
    "ambiguous_association",
    "source_unresolved",
    "extraction_failed",
]


class Tally(Aggregate):
    denominator: int = 0
    categories: dict[Category, int] = Field(default_factory=dict)
    present: int = 0
    absent: int = 0
    not_annotated: int = 0
    source_found: int = 0
    source_not_observed: int = 0
    source_unresolved: int = 0
    region_detected_on_label_page: int = 0
    candidate_emitted: int = 0
    resolved_value_emitted: int = 0
    associated_row_emitted: int = 0
    displaced_value_evidence: int = 0

    def add(
        self,
        category: Category,
        label: HumanField[Any],
        source: "SourceCheck",
        *,
        region: bool,
        candidate: bool,
        prediction: ExtractedField[Any] | None,
    ) -> None:
        self.denominator += 1
        self.categories[category] = self.categories.get(category, 0) + 1
        setattr(self, label.status, getattr(self, label.status) + 1)
        if label.status == "present":
            self.source_found += int(source.state == "found")
            self.source_not_observed += int(source.state == "tokens_not_observed")
            self.source_unresolved += int(source.state == "annotation_or_tokens_unresolved")
            self.region_detected_on_label_page += int(region)
            self.candidate_emitted += int(candidate)
            self.resolved_value_emitted += int(
                bool(prediction and prediction.status == ExtractionStatus.EXTRACTED)
            )


class Slice(Aggregate):
    documents: int = 0
    headers: dict[
        Literal["invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"], Tally
    ] = Field(default_factory=dict)
    cells: dict[Literal["description", "quantity", "unit_price", "line_total"], Tally] = Field(
        default_factory=dict
    )
    rows_denominator: int = 0
    rows: dict[RowCategory, int] = Field(default_factory=dict)
    predicted_rows: int = 0
    associated_predicted_rows: int = 0
    unassociated_predicted_rows: int = 0
    ambiguous_predicted_rows: int = 0
    predicted_rows_with_wrong_column_semantics: int = 0
    predicted_rows_with_displaced_cells: int = 0
    total_present: int = 0
    total_emitted: int = 0
    total_equals_subtotal: int = 0
    total_equals_subtotal_location_supported: int = 0
    total_subtotal_equal_labels: int = 0
    absent_tables: int = 0
    unannotated_tables: int = 0
    labelled_table_documents: int = 0
    labelled_table_documents_without_emitted_rows: int = 0
    labelled_table_documents_without_detected_header: int = 0
    visual_rows: int = 0
    visual_stages: dict[
        Literal[
            "header",
            "before_header",
            "footer",
            "ignored",
            "probable_item",
            "description_only",
            "missing_description",
            "no_numeric_support",
        ],
        int,
    ] = Field(default_factory=dict)


class Definitions(Aggregate):
    tally_denominator: Literal[
        "all label opportunities; present/absent scored; unannotated excluded"
    ] = "all label opportunities; present/absent scored; unannotated excluded"
    signals_denominator: Literal[
        "present labels only; stages are independent observable signals"
    ] = "present labels only; stages are independent observable signals"
    source: Literal[
        "unique minimal contiguous normalized token span inside human boxes; bounded probe"
    ] = "unique minimal contiguous normalized token span inside human boxes; bounded probe"
    regions: Literal["existing header-label or table-header detector on label page; not causal"] = (
        "existing header-label or table-header detector on label page; not causal"
    )
    row_identity: Literal[
        "unique evidence containment of labelled source tokens; no index or arithmetic"
    ] = "unique evidence containment of labelled source tokens; no index or arithmetic"
    confusion: Literal[
        "emitted total equals distinct present subtotal; location support separately counted"
    ] = "emitted total equals distinct present subtotal; location support separately counted"
    scorer_only: Literal[
        "location-associated exact row absent from order-preserving exact alignment"
    ] = "location-associated exact row absent from order-preserving exact alignment"


class AttributionReport(Aggregate):
    metric_version: Literal["real-input-attribution-v1"] = "real-input-attribution-v1"
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    extractor_version: Literal["0.2.0"] = "0.2.0"
    definitions: Definitions = Field(default_factory=Definitions)
    attempted_documents: int
    failed_documents: int
    pages: int
    ocr_documents: int
    ocr_available: bool
    slices: dict[Literal["all"] | Family, Slice]
    limitations: Literal["observational-development-audit-not-causal"] = (
        "observational-development-audit-not-causal"
    )


@dataclass
class Probe:
    candidates: dict[str, list[Any]] = field(default_factory=dict)
    region_pages: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))


@contextmanager
def observe_headers(probe: Probe, document: DocumentText) -> Iterator[None]:
    """Single-process instrumentation delegates unchanged to the real functions."""
    resolver = resolve_candidates
    money = header_rules._extract_labeled_money
    lines = reconstruct_lines(document)
    patterns = {
        "invoice_number": header_rules._INVOICE_NUMBER_LABEL,
        "invoice_date": header_rules._INVOICE_DATE_LABEL,
        "currency": header_rules._CURRENCY_CONTEXT,
    }
    for name, pattern in patterns.items():
        probe.region_pages[name].update(line.page for line in lines if pattern.search(line.text))

    def resolve(candidates: list[Any], **kwargs: Any) -> Any:
        name = kwargs["ambiguous_rule_id"].split(".")[1]
        probe.candidates[name] = list(candidates)
        return resolver(candidates, **kwargs)

    def labeled(lines: list[Any], **kwargs: Any) -> Any:
        exclusions = kwargs.get("exclusions")
        probe.region_pages[kwargs["field_name"]].update(
            line.page
            for line in lines
            if not (exclusions and exclusions.search(line.text))
            and any(pattern.search(line.text) for _, pattern, _ in kwargs["labels"])
        )
        return money(lines, **kwargs)

    with (
        patch.object(header_rules, "resolve_candidates", resolve),
        patch.object(header_rules, "_extract_labeled_money", labeled),
    ):
        yield


class TracedExtractor(DeterministicInvoiceExtractor):
    def __init__(self) -> None:
        self.probe = Probe()

    def extract(self, document: DocumentText) -> Invoice:
        with observe_headers(self.probe, document):
            return super().extract(document)


def contains(span: EvidenceSpan, word: WordToken) -> bool:
    return (
        span.page == word.page
        and span.bbox.x0 <= (word.bbox.x0 + word.bbox.x1) / 2 <= span.bbox.x1
        and span.bbox.y0 <= (word.bbox.y0 + word.bbox.y1) / 2 <= span.bbox.y1
    )


def normalized_source(text: str, name: str) -> str | None:
    if name in {"subtotal", "tax", "total", "quantity", "unit_price", "line_total"}:
        return canonical_value(parse_money(text), name)
    if name == "invoice_date":
        return canonical_value(parse_invoice_date(text), name)
    if name == "currency":
        return normalize_currency(text)
    return canonical_value(text, name)


def spans(words: list[WordToken], name: str, value: object) -> list[list[WordToken]]:
    target = canonical_value(value, name)
    matches: list[list[WordToken]] = []
    limit = 32 if name == "description" else 4
    for start in range(len(words)):
        for end in range(start + 1, min(len(words), start + limit) + 1):
            segment = words[start:end]
            if any(w.page != segment[0].page for w in segment):
                break
            if normalized_source(" ".join(w.text for w in segment), name) == target:
                matches.append(segment)
    # Nested spans containing the same value are not competing occurrences.
    return [
        m for m in matches if not any(len(n) < len(m) and all(w in m for w in n) for n in matches)
    ]


@dataclass
class SourceCheck:
    state: Literal["found", "tokens_not_observed", "annotation_or_tokens_unresolved"]
    words: list[WordToken]


def check_source(label: HumanField[Any], name: str, document: DocumentText) -> SourceCheck:
    words = [w for page in document.pages for w in page.words]
    located = [
        w
        for w in words
        if any(
            box.page == w.page
            and box.bbox.x0 <= (w.bbox.x0 + w.bbox.x1) / 2 <= box.bbox.x1
            and box.bbox.y0 <= (w.bbox.y0 + w.bbox.y1) / 2 <= box.bbox.y1
            for box in label.evidence
        )
    ]
    hits = spans(located, name, label.value)
    if len(hits) == 1:
        return SourceCheck("found", hits[0])
    if hits or len(located) > 32:
        return SourceCheck("annotation_or_tokens_unresolved", [])
    # Global presence cannot repair annotation boxes; it is only an unresolved signal.
    if any(spans(line.words, name, label.value) for line in reconstruct_lines(document)):
        return SourceCheck("annotation_or_tokens_unresolved", [])
    return SourceCheck("tokens_not_observed", [])


def bound(prediction: ExtractedField[Any], source: SourceCheck) -> bool:
    return bool(source.words) and all(
        any(contains(s, w) for s in prediction.evidence) for w in source.words
    )


def classify(
    label: HumanField[Any],
    name: str,
    prediction: ExtractedField[Any] | None,
    source: SourceCheck,
    *,
    region: bool,
    candidates: int,
    other_role: bool = False,
    wrong_row: bool = False,
    scorer_rejected: bool = False,
) -> Category:
    if label.status == "not_annotated":
        return "excluded_unannotated"
    if label.status == "absent":
        return (
            "false_on_absent" if prediction and prediction.value is not None else "correct_absence"
        )
    if source.state != "found":
        return source.state
    if prediction and prediction.status == ExtractionStatus.AMBIGUOUS:
        return "ambiguous_candidate"
    if prediction and prediction.status == ExtractionStatus.EXTRACTED:
        if wrong_row:
            return "wrong_row"
        if other_role:
            return "wrong_role"
        if canonical_value(prediction.value, name) != canonical_value(label.value, name):
            return "wrong_value"
        if not bound(prediction, source):
            return "evidence_unresolved"
        return "scorer_only" if scorer_rejected else "correct"
    if not region:
        return "region_not_detected"
    return "candidate_not_emitted" if not candidates else "ambiguous_candidate"


def family(document: DocumentText | None, detected: bool) -> Family:
    if document is None:
        return "unscorable"
    tokens = {w.text.casefold().strip(".,:()") for p in document.pages for w in p.words}
    if {"net", "tax", "gross"} <= tokens:
        return "net_tax_gross_token_signature"
    return "other_detected_table" if detected else "no_detected_table_header"


def reconcile(part: Slice) -> None:
    for tally in [*part.headers.values(), *part.cells.values()]:
        if tally.denominator != sum(tally.categories.values()):
            raise ValueError("Attribution accounting failed")
        if tally.denominator != tally.present + tally.absent + tally.not_annotated:
            raise ValueError("Label status accounting failed")
        if (
            tally.present
            != tally.source_found + tally.source_not_observed + tally.source_unresolved
        ):
            raise ValueError("Source accounting failed")
    if part.rows_denominator != sum(part.rows.values()):
        raise ValueError("Row accounting failed")
    if (
        part.predicted_rows
        != part.associated_predicted_rows
        + part.unassociated_predicted_rows
        + part.ambiguous_predicted_rows
    ):
        raise ValueError("Prediction accounting failed")


def analyze(
    annotation: HumanInvoiceAnnotation,
    document: DocumentText | None,
    invoice: Invoice | None,
    probe: Probe,
) -> tuple[Family, Slice, dict[str, Any]]:
    part = Slice(documents=1)
    trace = trace_line_parser(document, invoice.line_items if invoice else []) if document else None
    group = family(document, bool(trace and trace.page_has_header))
    private: dict[str, Any] = {"headers": {}, "cells": [], "rows": []}
    sources = {
        name: check_source(getattr(annotation, name), name, document)
        for name in HEADER_FIELDS
        if document and getattr(annotation, name).status == "present"
    }
    for name in HEADER_FIELDS:
        label = getattr(annotation, name)
        prediction = getattr(invoice, name) if invoice else None
        source = sources.get(name, SourceCheck("annotation_or_tokens_unresolved", []))
        other = bool(
            prediction
            and label.status == "present"
            and any(
                other_name != name
                and getattr(annotation, other_name).status == "present"
                and canonical_value(getattr(annotation, other_name).value, name)
                != canonical_value(label.value, name)
                and canonical_value(prediction.value, name)
                == canonical_value(getattr(annotation, other_name).value, name)
                and bound(prediction, sources[other_name])
                for other_name in sources
            )
        )
        category = classify(
            label,
            name,
            prediction,
            source,
            region=bool({b.page for b in label.evidence} & probe.region_pages[name]),
            candidates=len(probe.candidates.get(name, [])),
            other_role=other,
        )
        if invoice is None and label.status != "not_annotated":
            category = "extraction_failed"
        part.headers[name] = Tally()  # type: ignore[index]
        part.headers[name].add(  # type: ignore[index]
            category,
            label,
            source,
            region=bool({b.page for b in label.evidence} & probe.region_pages[name]),
            candidate=bool(probe.candidates.get(name)),
            prediction=prediction,
        )
        private["headers"][name] = dict(
            category=category,
            source=source.state,
            candidate_count=len(probe.candidates.get(name, [])),
            region_pages=sorted(probe.region_pages[name]),
        )
    total, subtotal = annotation.total, annotation.subtotal
    part.total_present = int(total.status == "present")
    part.total_emitted = int(
        total.status == "present"
        and invoice is not None
        and invoice.total.status == ExtractionStatus.EXTRACTED
    )
    if total.status == subtotal.status == "present":
        same = canonical_value(total.value, "total") == canonical_value(subtotal.value, "total")
        part.total_subtotal_equal_labels = int(same)
        if invoice and invoice.total.status == ExtractionStatus.EXTRACTED and not same:
            part.total_equals_subtotal = int(
                canonical_value(invoice.total.value, "total")
                == canonical_value(subtotal.value, "total")
            )
            part.total_equals_subtotal_location_supported = int(
                bool(part.total_equals_subtotal) and bound(invoice.total, sources["subtotal"])
            )
    part.absent_tables = int(annotation.line_items.status == "absent")
    part.unannotated_tables = int(annotation.line_items.status == "not_annotated")
    rows = annotation.line_items.rows
    predictions = invoice.line_items if invoice else []
    part.labelled_table_documents = int(annotation.line_items.status == "present")
    part.labelled_table_documents_without_emitted_rows = int(bool(rows) and not predictions)
    part.labelled_table_documents_without_detected_header = int(
        bool(rows) and not (trace and trace.page_has_header)
    )
    checks = [
        {
            name: check_source(getattr(row, name), name, document)
            for name in LINE_FIELDS
            if document and getattr(row, name).status == "present"
        }
        for row in rows
    ]
    # Row identity uses source location only, never list position, value equality or arithmetic.
    links: dict[int, list[int]] = {}
    for p, candidate_line in enumerate(predictions):
        anchors = [
            i
            for i, row_checks in enumerate(checks)
            if any(
                bound(getattr(candidate_line, name), source) for name, source in row_checks.items()
            )
        ]
        links[p] = anchors
    reverse: dict[int, list[int]] = defaultdict(list)
    for p, anchors in links.items():
        if len(anchors) == 1:
            reverse[anchors[0]].append(p)
    exact_alignment = {
        a.ground_truth_index
        for a in align_line_items(annotation.legacy_truth().line_items, predictions)
        if a.exact
    }
    associated = {
        p for p, anchors in links.items() if len(anchors) == 1 and len(reverse[anchors[0]]) == 1
    }
    ambiguous = {
        p
        for p, anchors in links.items()
        if len(anchors) > 1 or (len(anchors) == 1 and len(reverse[anchors[0]]) > 1)
    }
    part.predicted_rows = len(predictions)
    part.associated_predicted_rows = len(associated)
    part.ambiguous_predicted_rows = len(ambiguous)
    part.unassociated_predicted_rows = len(predictions) - len(associated) - len(ambiguous)
    wrong_columns: set[int] = set()
    displaced: set[int] = set()
    for i, row in enumerate(rows):
        indices = reverse.get(i, [])
        matched_index = indices[0] if len(indices) == 1 and indices[0] in associated else None
        predicted = predictions[matched_index] if matched_index is not None else None
        row_checks = checks[i]
        scorer_only = bool(
            predicted
            and is_exact_line_item(annotation.legacy_truth().line_items[i], predicted)
            and i not in exact_alignment
        )
        if invoice is None:
            stage: RowCategory = "extraction_failed"
        elif any(source.state != "found" for source in row_checks.values()) or any(
            getattr(row, n).status == "not_annotated" for n in LINE_FIELDS
        ):
            stage = "source_unresolved"
        elif any(i in anchors for p0, anchors in links.items() if p0 in ambiguous):
            stage = "ambiguous_association"
        elif predicted:
            stage = (
                "scorer_only"
                if scorer_only
                else "exact"
                if is_exact_line_item(annotation.legacy_truth().line_items[i], predicted)
                else "wrong_row_values"
            )
        elif not trace or not (
            {b.page for n in LINE_FIELDS for b in getattr(row, n).evidence} & trace.page_has_header
        ):
            stage = "no_detected_header"
        else:
            stage = "detected_no_associated_row"
        part.rows_denominator += 1
        part.rows[stage] = part.rows.get(stage, 0) + 1
        private["rows"].append(dict(stage=stage, associated_prediction=matched_index))
        cells = {}
        for name in LINE_FIELDS:
            label = getattr(row, name)
            cell = getattr(predicted, name) if predicted else None
            source = row_checks.get(name, SourceCheck("annotation_or_tokens_unresolved", []))
            other_role = bool(
                cell
                and any(
                    other != name
                    and canonical_value(getattr(row, other).value, name)
                    != canonical_value(label.value, name)
                    and canonical_value(cell.value, name)
                    == canonical_value(getattr(row, other).value, name)
                    and bound(cell, other_source)
                    for other, other_source in row_checks.items()
                )
            )
            wrong_row = bool(
                cell
                and source.state == "found"
                and not bound(cell, source)
                and any(
                    j != i and name in other_checks and bound(cell, other_checks[name])
                    for j, other_checks in enumerate(checks)
                )
            )
            if other_role and matched_index is not None:
                wrong_columns.add(matched_index)
            category = classify(
                label,
                name,
                cell,
                source,
                region=bool(trace and {b.page for b in label.evidence} & trace.page_has_header),
                candidates=int(bool(cell and cell.value is not None)),
                other_role=other_role,
                wrong_row=wrong_row,
                scorer_rejected=scorer_only,
            )
            if invoice is None and label.status != "not_annotated":
                category = "extraction_failed"
            elif label.status == "absent" and predicted is None:
                category = "absence_unscorable"
            elif (
                stage == "ambiguous_association"
                and label.status == "present"
                and source.state == "found"
            ):
                category = "evidence_unresolved"
            part.cells.setdefault(name, Tally()).add(  # type: ignore[arg-type]
                category,
                label,
                source,
                region=bool(trace and {b.page for b in label.evidence} & trace.page_has_header),
                candidate=bool(cell and cell.value is not None),
                prediction=cell,
            )
            tally = part.cells[name]  # type: ignore[index]
            if label.status == "present":
                tally.associated_row_emitted += int(predicted is not None)
                is_displaced = bool(
                    cell
                    and cell.status == ExtractionStatus.EXTRACTED
                    and source.state == "found"
                    and not bound(cell, source)
                )
                tally.displaced_value_evidence += int(is_displaced)
                if is_displaced and matched_index is not None:
                    displaced.add(matched_index)
            cells[name] = dict(category=category, source=source.state)
        private["cells"].append(cells)
    part.predicted_rows_with_wrong_column_semantics = len(wrong_columns)
    part.predicted_rows_with_displaced_cells = len(displaced)
    if trace:
        part.visual_rows = len(trace.rows)
        part.visual_stages = dict(Counter(trace.row_stages))  # type: ignore[assignment]
        private["visual_stage_counts"] = dict(trace.counts)
        private["visual_row_stages"] = trace.row_stages
    reconcile(part)
    return group, part, private


def combine(parts: list[Slice]) -> Slice:
    result = Slice()
    for part in parts:
        for key in Slice.model_fields:
            if key in {"headers", "cells"}:
                target = getattr(result, key)
                for name, tally in getattr(part, key).items():
                    merged = target.setdefault(name, Tally())
                    merged.denominator += tally.denominator
                    merged.categories = dict(Counter(merged.categories) + Counter(tally.categories))
                    for signal in Tally.model_fields:
                        if signal not in {"denominator", "categories"}:
                            setattr(
                                merged, signal, getattr(merged, signal) + getattr(tally, signal)
                            )
            elif key in {"rows", "visual_stages"}:
                setattr(
                    result, key, dict(Counter(getattr(result, key)) + Counter(getattr(part, key)))
                )
            else:
                setattr(result, key, getattr(result, key) + getattr(part, key))
    reconcile(result)
    return result


def run_attribution(
    manifest: Path, output: Path, diagnostics: Path, *, repository: Path
) -> AttributionReport:
    output = fresh_public(output, repository)
    diagnostics = private_path(diagnostics, repository)
    if diagnostics.exists():
        raise FileExistsError("Private diagnostics require a fresh directory")
    manifest = private_path(manifest, repository)
    dataset = ManifestAdapter().load(manifest)
    if dataset.examples[0].split != "development":
        raise ValueError("Attribution is observed development evaluation only")
    prepared = []
    hashes = []
    for example in dataset.examples:
        body = member(manifest.parent, example.document_path, repository).read_bytes()
        annotation = HumanInvoiceAnnotation.model_validate_json(
            member(manifest.parent, example.ground_truth_path, repository).read_bytes()
        )
        canonical = annotation.model_dump_json().encode()
        hashes.append(bytes.fromhex(_length_delimited_hash([body, canonical])))
        prepared.append((example, body, annotation, canonical))
    by_family: dict[Family, list[Slice]] = defaultdict(list)
    cases = []
    failed = pages = ocr = 0
    with quiet_extraction():
        runtime = inspect_ocr_runtime()
        for example, body, annotation, canonical in prepared:
            observed = ObservedTextExtractor(runtime)
            extractor = TracedExtractor()
            result = EvaluationRunner(
                text_extractor=observed, invoice_extractor=extractor
            )._evaluate(example, body, annotation.legacy_truth(), canonical)
            if observed.page_count is not None and any(
                box.page >= observed.page_count
                for label in [
                    *(getattr(annotation, n) for n in HEADER_FIELDS),
                    *(getattr(r, n) for r in annotation.line_items.rows for n in LINE_FIELDS),
                ]
                for box in label.evidence
            ):
                raise ValueError("Annotation page outside source")
            group, part, private = analyze(
                annotation, observed.document, result.prediction.invoice, extractor.probe
            )
            by_family[group].append(part)
            failed += int(not result.prediction.schema_valid)
            pages += observed.page_count or 0
            ocr += int(observed.ocr_pages > 0)
            cases.append(
                dict(
                    document_id=example.document_id,
                    family=group,
                    analysis=private,
                    result=result.model_dump(mode="json"),
                    annotation=annotation.model_dump(mode="json"),
                    candidates={
                        k: [c.model_dump(mode="json") for c in v]
                        for k, v in extractor.probe.candidates.items()
                    },
                )
            )
    revision, state = source_state(repository)
    report = AttributionReport(
        corpus_fingerprint=_length_delimited_hash(sorted(hashes)),
        source_revision=revision,
        source_state=state,
        attempted_documents=len(prepared),
        failed_documents=failed,
        pages=pages,
        ocr_documents=ocr,
        ocr_available=runtime.available,
        slices={
            "all": combine([p for parts in by_family.values() for p in parts]),
            **{k: combine(v) for k, v in by_family.items()},
        },
    )
    payload = report.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=False)
    diagnostics.mkdir(parents=True, exist_ok=False)
    (diagnostics / "cases.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8"
    )
    (output / "report.json").write_text(payload, encoding="utf-8")
    (output / "report.md").write_text(
        "# Private invoice failure attribution\n\n"
        "Evaluation-only observational stages, not confirmed root causes. "
        "The sample is observed development data. See the failure-attribution guide "
        "for definitions, denominators and limitations. No arithmetic or model calls.\n\n```json\n"
        + payload
        + "```\n",
        encoding="utf-8",
    )
    return report
