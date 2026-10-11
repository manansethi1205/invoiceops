"""Opt-in source-only total-role guard; never registered in production selection."""

import re
from decimal import Decimal
from statistics import median
from typing import Literal

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.normalization import parse_money
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.table_layout import VisualRow, reconstruct_visual_rows
from invoiceops.schemas.extraction import (
    DocumentText,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    WordToken,
)

GUARD_NAME: Literal["deterministic-financial-summary-guard"] = (
    "deterministic-financial-summary-guard"
)
GUARD_VERSION: Literal["0.3.0"] = "0.3.0"
_GENERIC_RULES = {"header.total.total.same_line.v1", "header.total.total.next_line.v1"}
_ROLE = re.compile(r"^(?:net|tax|gross|vat|gst|subtotal|taxable|payable)$", re.IGNORECASE)
_GROSS = re.compile(r"^(?:gross|payable)$", re.IGNORECASE)


def _label(word: WordToken) -> str:
    return word.text.strip(" .:;()")


def _inside(word: WordToken, total: ExtractedField[Decimal]) -> bool:
    return any(
        span.page == word.page
        and span.source == word.source
        and span.bbox.x0 <= (word.bbox.x0 + word.bbox.x1) / 2 <= span.bbox.x1
        and span.bbox.y0 <= (word.bbox.y0 + word.bbox.y1) / 2 <= span.bbox.y1
        for span in total.evidence
    )


def _money_spans(words: list[WordToken]) -> list[list[WordToken]]:
    """Complete bounded numeric spans, including split currency/number tokens."""
    matches = []
    for start in range(len(words)):
        for end in range(start + 1, min(len(words), start + 4) + 1):
            selected = words[start:end]
            if any(w.page != selected[0].page for w in selected):
                break
            # Do not concatenate spatially separate financial columns into one number.
            if any(
                right.bbox.x0 - left.bbox.x1
                > 2 * max(left.bbox.y1 - left.bbox.y0, right.bbox.y1 - right.bbox.y0)
                for left, right in zip(selected, selected[1:], strict=False)
            ):
                break
            numeric = [w for w in selected if any(c.isdigit() for c in w.text)]
            if len(numeric) > 1 and not any(
                w.text in {",", "."} or w.text.endswith((",", ".")) or w.text.startswith((",", "."))
                for w in selected
            ):
                continue
            if parse_money("".join(w.text for w in selected)) is not None:
                matches.append(selected)
    return [
        m for m in matches if not any(len(n) > len(m) and all(w in n for w in m) for n in matches)
    ]


def _ambiguous(words: list[WordToken], reason: str) -> ExtractedField[Decimal]:
    return ExtractedField[Decimal](
        value=None,
        status=ExtractionStatus.AMBIGUOUS,
        evidence=evidence_from_words(words) if words else [],
        rule_id=f"financial_summary.{reason}.v1",
    )


def guard_total(total: ExtractedField[Decimal], document: DocumentText) -> ExtractedField[Decimal]:
    if total.status != ExtractionStatus.EXTRACTED or total.value is None:
        return total  # Preserve missing and conservative ambiguity, including its evidence.
    rows = reconstruct_visual_rows(document)
    matches: list[tuple[VisualRow, list[WordToken]]] = []
    for row in rows:
        quoted = [w for w in row.words if _inside(w, total)]
        for span in _money_spans(quoted):
            if parse_money("".join(w.text for w in span)) == total.value:
                matches.append((row, span))
    if len(matches) != 1:
        quoted = [w for row in rows for w in row.words if _inside(w, total)]
        return _ambiguous(quoted, "unbound_or_repeated_value")
    row, selected = matches[0]
    if total.rule_id not in _GENERIC_RULES:
        return total  # This slice does not adjudicate explicit-total or hybrid promotions.
    amounts = _money_spans(row.words)
    if len(amounts) <= 1:
        return total
    height = median(w.bbox.y1 - w.bbox.y0 for w in row.words)
    left = min(w.bbox.x0 for span in amounts for w in span)
    right = max(w.bbox.x1 for span in amounts for w in span)
    nearby = [
        other
        for other in rows
        if other.page == row.page
        and abs((other.y0 + other.y1) / 2 - (row.y0 + row.y1) / 2) <= 8 * height
        and any(
            _ROLE.fullmatch(_label(w))
            and left - 2 * height <= (w.bbox.x0 + w.bbox.x1) / 2 <= right + 2 * height
            for w in other.words
        )
    ]
    inline_roles = [w for w in row.words if _ROLE.fullmatch(_label(w))]
    # Multiple complete amounts under a generic Total do not establish an invoice-total
    # role even when nearby role labels are absent/unreadable. Abstain rather than
    # treating the first/last numeric column as authoritative. Nearby prose on a
    # different row cannot trigger this gate when the Total row has one amount.
    # Direct printed gross/payable label immediately before this specific amount is the
    # only supported promotion-preserving proof in a competing summary. Column-header
    # inference, equality to another extracted field, and arithmetic are deliberately absent.
    gross = [w for w in inline_roles if _GROSS.fullmatch(_label(w))]
    if len(gross) == 1:
        label = gross[0]
        between = [w for w in row.words if label.bbox.x1 <= w.bbox.x0 < selected[0].bbox.x0]
        if (
            0 <= selected[0].bbox.x0 - label.bbox.x1 <= 4 * height
            and all(_label(w).casefold() in {"amount", "total", ":"} for w in between)
            and not any(w.bbox.x1 <= label.bbox.x0 for w in selected)
        ):
            return total.model_copy(
                update={
                    "evidence": evidence_from_words(selected),
                    "rule_id": "financial_summary.inline_gross_unique.v1",
                }
            )
    bounded = list(row.words)
    for other in nearby:
        bounded.extend(w for w in other.words if w not in bounded)
    reason = "competing_amount_roles" if nearby or inline_roles else "unresolved_multi_amount_total"
    return _ambiguous(bounded, reason)


class FinancialSummaryGuardExtractor(DeterministicInvoiceExtractor):
    name = GUARD_NAME
    version = GUARD_VERSION

    def extract(self, document: DocumentText) -> Invoice:
        invoice = super().extract(document)
        return invoice.model_copy(update={"total": guard_total(invoice.total, document)})
