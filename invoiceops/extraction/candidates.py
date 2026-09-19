from collections.abc import Callable, Hashable

from pydantic import BaseModel, Field

from invoiceops.schemas.extraction import EvidenceSpan, ExtractedField, ExtractionStatus


class FieldCandidate[T](BaseModel):
    value: T
    evidence: list[EvidenceSpan] = Field(min_length=1)
    rule_id: str
    priority: int


def _unique_evidence(spans: list[EvidenceSpan]) -> list[EvidenceSpan]:
    seen: set[tuple[object, ...]] = set()
    result: list[EvidenceSpan] = []
    for span in spans:
        key = (
            span.page,
            span.bbox.x0,
            span.bbox.y0,
            span.bbox.x1,
            span.bbox.y1,
            span.text,
            span.source,
        )
        if key not in seen:
            seen.add(key)
            result.append(span)
    return result


def resolve_candidates[T](
    candidates: list[FieldCandidate[T]],
    *,
    comparison_key: Callable[[T], Hashable],
    ambiguous_rule_id: str,
) -> ExtractedField[T]:
    if not candidates:
        return ExtractedField[T](
            value=None,
            status=ExtractionStatus.MISSING,
            evidence=[],
            rule_id=None,
        )

    highest_priority = max(candidate.priority for candidate in candidates)
    top = [candidate for candidate in candidates if candidate.priority == highest_priority]
    grouped: dict[Hashable, list[FieldCandidate[T]]] = {}
    for candidate in top:
        grouped.setdefault(comparison_key(candidate.value), []).append(candidate)

    if len(grouped) > 1:
        return ExtractedField[T](
            value=None,
            status=ExtractionStatus.AMBIGUOUS,
            evidence=_unique_evidence(
                [span for candidate in top for span in candidate.evidence]
            ),
            rule_id=ambiguous_rule_id,
        )

    selected = top[0]
    same_value = next(iter(grouped.values()))
    return ExtractedField[T](
        value=selected.value,
        status=ExtractionStatus.EXTRACTED,
        evidence=_unique_evidence(
            [span for candidate in same_value for span in candidate.evidence]
        ),
        rule_id=selected.rule_id,
    )
