import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from rapidfuzz.fuzz import ratio

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.hybrid.schemas import CandidateField, GroundingReason
from invoiceops.extraction.normalization import (
    normalize_currency,
    normalize_whitespace,
    parse_invoice_date,
    parse_money,
)
from invoiceops.schemas.extraction import DocumentText, EvidenceSpan, WordToken

type NormalizedValue = str | date | Decimal


@dataclass(frozen=True)
class GroundingResult:
    reason: GroundingReason
    normalized_value: NormalizedValue | None
    evidence: tuple[EvidenceSpan, ...] = ()

    @property
    def grounded(self) -> bool:
        return self.reason in {GroundingReason.GROUNDED_EXACT, GroundingReason.GROUNDED_FUZZY}


def _parts(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)


def _page_stream(words: list[WordToken]) -> tuple[list[str], list[int]]:
    parts: list[str] = []
    owners: list[int] = []
    for index, word in enumerate(words):
        for part in _parts(word.text):
            parts.append(part)
            owners.append(index)
    return parts, owners


def _normalize_value(field_name: str, raw: str) -> NormalizedValue | None:
    if field_name == "invoice_date":
        return parse_invoice_date(raw)
    if field_name == "currency":
        return normalize_currency(raw)
    if field_name in {"subtotal", "tax", "total", "quantity", "unit_price", "line_total"}:
        return parse_money(raw)
    value = normalize_whitespace(raw)
    return value or None


def ground_candidate(
    field_name: str,
    candidate: CandidateField,
    document: DocumentText,
    *,
    fuzzy_threshold: float = 92.0,
) -> GroundingResult:
    if candidate.raw_value is None:
        return GroundingResult(GroundingReason.QUOTE_NOT_FOUND, None)
    normalized_value = _normalize_value(field_name, candidate.raw_value)
    if normalized_value is None:
        return GroundingResult(GroundingReason.VALUE_NORMALIZATION_FAILED, None)
    if candidate.page is None or candidate.page >= len(document.pages):
        return GroundingResult(GroundingReason.PAGE_OUT_OF_RANGE, normalized_value)
    if not candidate.evidence_quote or not candidate.evidence_quote.strip():
        return GroundingResult(GroundingReason.QUOTE_NOT_FOUND, normalized_value)

    page = document.pages[candidate.page]
    words = sorted(
        page.words,
        key=lambda word: (word.bbox.y0, word.bbox.x0, word.block_number, word.line_number),
    )
    stream, owners = _page_stream(words)
    quote = _parts(candidate.evidence_quote)
    if not quote:
        return GroundingResult(GroundingReason.QUOTE_NOT_FOUND, normalized_value)
    exact_starts = [
        start
        for start in range(len(stream) - len(quote) + 1)
        if stream[start : start + len(quote)] == quote
        and _word_boundary_aligned(owners, start, len(quote))
    ]
    if len(exact_starts) > 1:
        return GroundingResult(GroundingReason.QUOTE_NOT_UNIQUE, normalized_value)
    if len(exact_starts) == 1:
        return _grounded(words, owners, exact_starts[0], len(quote), normalized_value, False)

    quote_text = " ".join(quote)
    scored: list[tuple[float, int, int]] = []
    for length in range(max(1, len(quote) - 1), len(quote) + 2):
        for start in range(len(stream) - length + 1):
            if not _word_boundary_aligned(owners, start, length):
                continue
            score = float(ratio(quote_text, " ".join(stream[start : start + length])))
            if score >= fuzzy_threshold:
                scored.append((score, start, length))
    if not scored:
        return GroundingResult(GroundingReason.QUOTE_NOT_FOUND, normalized_value)
    best_score = max(item[0] for item in scored)
    best = {(start, length) for score, start, length in scored if score == best_score}
    if len(best) != 1:
        return GroundingResult(GroundingReason.QUOTE_NOT_UNIQUE, normalized_value)
    start, length = next(iter(best))
    return _grounded(words, owners, start, length, normalized_value, True)


def _word_boundary_aligned(owners: list[int], start: int, length: int) -> bool:
    end = start + length
    starts_at_boundary = start == 0 or owners[start - 1] != owners[start]
    ends_at_boundary = end == len(owners) or owners[end - 1] != owners[end]
    return starts_at_boundary and ends_at_boundary


def _grounded(
    words: list[WordToken],
    owners: list[int],
    start: int,
    length: int,
    value: NormalizedValue,
    fuzzy: bool,
) -> GroundingResult:
    indexes = list(dict.fromkeys(owners[start : start + length]))
    evidence = tuple(evidence_from_words([words[index] for index in indexes]))
    return GroundingResult(
        GroundingReason.GROUNDED_FUZZY if fuzzy else GroundingReason.GROUNDED_EXACT,
        value,
        evidence,
    )
