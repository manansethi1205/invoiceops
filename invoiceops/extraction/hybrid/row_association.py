"""Conservative source-evidence association; never infer identity from values or order."""

from collections import Counter

from invoiceops.extraction.hybrid.grounding import GroundingResult
from invoiceops.schemas.extraction import DocumentText, EvidenceSpan, InvoiceLine


def _tokens(
    spans: list[EvidenceSpan] | tuple[EvidenceSpan, ...], document: DocumentText
) -> set[tuple[int, int]]:
    return {
        (page.page, index)
        for page in document.pages
        for index, word in enumerate(page.words)
        for span in spans
        if span.page == page.page == word.page
        and word.source == span.source
        and span.bbox.x0 <= (word.bbox.x0 + word.bbox.x1) / 2 <= span.bbox.x1
        and span.bbox.y0 <= (word.bbox.y0 + word.bbox.y1) / 2 <= span.bbox.y1
    }


def _overlap(a: EvidenceSpan, b: EvidenceSpan) -> bool:
    return a.page == b.page and min(a.bbox.y1, b.bbox.y1) > max(a.bbox.y0, b.bbox.y0)


def associate_rows(
    deterministic: list[InvoiceLine],
    rows: list[dict[str, GroundingResult]],
    document: DocumentText,
) -> tuple[dict[int, int], list[str]]:
    anchors = [_tokens(line.description.evidence, document) for line in deterministic]
    row_tokens = [
        set().union(*(_tokens(cell.evidence, document) for cell in row.values())) for row in rows
    ]
    usage = Counter(token for tokens in row_tokens for token in tokens)
    proposals: dict[int, int] = {}
    reasons: list[str] = []
    for index, row in enumerate(rows):
        description = row.get("description")
        reason = "anchor_missing"
        if description is None or not description.grounded:
            reasons.append(reason)
            continue
        spans = description.evidence
        all_spans = [span for cell in row.values() for span in cell.evidence]
        pages = {span.page for span in all_spans}
        if any(not cell.grounded for cell in row.values()):
            reason = "cell_ungrounded"
        elif (
            len(pages) != 1
            or not spans
            or max((span.bbox.y1 for span in all_spans), default=1)
            - min((span.bbox.y0 for span in all_spans), default=0)
            > 0.06
        ):
            reason = "incoherent_geometry"
        elif any(
            not any(_overlap(span, anchor) for anchor in spans)
            for cell in row.values()
            for span in cell.evidence
        ):
            reason = "cross_row_cells"
        elif any(usage[token] > 1 for token in row_tokens[index]):
            reason = "reused_evidence"
        else:
            cell_sets = [_tokens(cell.evidence, document) for cell in row.values()]
            if any(a & b for i, a in enumerate(cell_sets) for b in cell_sets[i + 1 :]):
                reasons.append("reused_evidence")
                continue
            source_anchor = _tokens(spans, document)
            matches = [i for i, anchor in enumerate(anchors) if source_anchor & anchor]
            # A wrapped/broad anchor must not touch another deterministic row.
            spatial_matches = [
                i
                for i, line in enumerate(deterministic)
                if any(_overlap(a, b) for a in spans for b in line.description.evidence)
            ]
            other_rows_touched = any(
                _overlap(cell, anchor)
                for i, line in enumerate(deterministic)
                if i not in matches
                for anchor in line.description.evidence
                for cell in all_spans
            )
            if len(matches) == 1 and spatial_matches == matches and not other_rows_touched:
                proposals[index] = matches[0]
                reason = "associated"
            else:
                reason = "ambiguous_anchor" if matches else "candidate_only"
        reasons.append(reason)
    counts = Counter(proposals.values())
    associations: dict[int, int] = {}
    for candidate_index, deterministic_index in proposals.items():
        if counts[deterministic_index] == 1:
            associations[deterministic_index] = candidate_index
        else:
            reasons[candidate_index] = "ambiguous_anchor"
    return associations, reasons
