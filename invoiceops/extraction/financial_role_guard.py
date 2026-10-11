"""Opt-in 0.4.0 source-role candidate; frozen 0.3.0 remains unchanged."""

import re
from decimal import Decimal
from statistics import median
from typing import Literal

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.financial_summary_guard import (
    GUARD_NAME,
    _ambiguous,
    _inside,
    _label,
    _money_spans,
    guard_total,
)
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

ROLE_GUARD_VERSION: Literal["0.4.0"] = "0.4.0"
_PAYABLE = {"amount_due", "total_payable", "net_payable"}
_GROSS_LABEL = re.compile(
    r"^(?:grand total|invoice total|gross (?:invoice )?(?:total|amount))$", re.I
)
_FINANCIAL = re.compile(
    r"^(?:net|tax|gross|vat|gst|subtotal|taxable|payable|credit|prepayment)$", re.I
)


def _x_height(row: VisualRow, document: DocumentText, height: float) -> float:
    page = next(p for p in document.pages if p.page == row.page)
    return height * page.height / page.width


def _positive_geometry(row: VisualRow) -> bool:
    return all(w.bbox.x1 > w.bbox.x0 and w.bbox.y1 > w.bbox.y0 for w in row.words)


def _gross_proofs(
    rows: list[VisualRow], payable: VisualRow, document: DocumentText
) -> list[ExtractedField[Decimal]] | None:
    proofs = []
    for row in rows:
        height = median(w.bbox.y1 - w.bbox.y0 for w in payable.words)
        if row.page != payable.page or abs((row.y0 + row.y1 - payable.y0 - payable.y1) / 2) > (
            12 * height
        ):
            continue
        if not re.search(
            r"\b(?:gross|grand total|invoice total)\b", " ".join(_label(w) for w in row.words), re.I
        ):
            continue
        amounts = _money_spans(row.words)
        if not _positive_geometry(row):
            return None
        # Independent explicit proof must be a single labelled amount, not a column guess.
        if len(amounts) != 1:
            return None
        amount = amounts[0]
        before = [w for w in row.words if w.bbox.x1 <= amount[0].bbox.x0]
        after = [w for w in row.words if w.bbox.x0 >= amount[-1].bbox.x1]
        height = median(w.bbox.y1 - w.bbox.y0 for w in row.words)
        x_height = _x_height(row, document, height)
        if (
            not before
            or after
            or not _GROSS_LABEL.fullmatch(" ".join(_label(w) for w in before))
            or not 0 <= amount[0].bbox.x0 - before[-1].bbox.x1 <= 8 * x_height
            or len({w.source for w in row.words}) != 1
            or max((w.bbox.y0 + w.bbox.y1) / 2 for w in row.words)
            - min((w.bbox.y0 + w.bbox.y1) / 2 for w in row.words)
            > height / 4
        ):
            return None
        proofs.append(
            ExtractedField[Decimal](
                value=parse_money("".join(w.text for w in amount)),
                status=ExtractionStatus.EXTRACTED,
                evidence=evidence_from_words(row.words),
                rule_id="financial_role.explicit_gross_unique.v1",
            )
        )
    return proofs


def _without_reference(
    row: VisualRow, selected: list[WordToken], rows: list[VisualRow], document: DocumentText
) -> VisualRow | None:
    """A right-hand reference panel requires printed ID label and an empty source gutter."""
    labels = [w for w in row.words if _label(w).casefold() == "reference"]
    if len(labels) != 1 or not _positive_geometry(row):
        return None
    label = labels[0]
    height = median(w.bbox.y1 - w.bbox.y0 for w in row.words)
    x_height = _x_height(row, document, height)
    right = [w for w in row.words if w.bbox.x0 >= label.bbox.x0]
    tail = right[1:]
    if tail and _label(tail[0]).casefold() in {"id", "number", "no"}:
        tail = tail[1:]
    # Numeric identifiers only; currency, decimal punctuation, signs and prose are uncertain.
    if len(tail) != 1 or not tail[0].text.isascii() or not tail[0].text.isdigit():
        return None
    financial = [w for w in row.words if w.bbox.x1 < label.bbox.x0]
    if not financial or any(w not in financial for w in selected):
        return None
    edge = max(w.bbox.x1 for w in financial)
    if (
        label.bbox.x0 - edge < 6 * x_height
        or not 0 <= tail[0].bbox.x0 - right[-2].bbox.x1 <= 4 * x_height
        or len({w.source for w in row.words}) != 1
        or {(w.block_number, w.line_number) for w in financial}
        & {(w.block_number, w.line_number) for w in right}
        or max((w.bbox.y0 + w.bbox.y1) / 2 for w in row.words)
        - min((w.bbox.y0 + w.bbox.y1) / 2 for w in row.words)
        > height / 4
    ):
        return None
    nearby = [
        w
        for r in rows
        if r.page == row.page and abs((r.y0 + r.y1 - row.y0 - row.y1) / 2) <= 4 * height
        for w in r.words
    ]
    if any(
        w.bbox.x0 < label.bbox.x0
        and w.bbox.x1 > edge
        or w.bbox.x0 >= label.bbox.x0
        and _FINANCIAL.fullmatch(_label(w))
        for w in nearby
    ):
        return None
    return VisualRow(page=row.page, y0=row.y0, y1=row.y1, words=financial)


def role_guard_total(
    total: ExtractedField[Decimal], document: DocumentText
) -> ExtractedField[Decimal]:
    if total.status != ExtractionStatus.EXTRACTED or total.value is None:
        return total
    rows = reconstruct_visual_rows(document)
    matches = [
        (row, span)
        for row in rows
        for span in _money_spans([w for w in row.words if _inside(w, total)])
        if parse_money("".join(w.text for w in span)) == total.value
    ]
    if len(matches) != 1:
        return guard_total(total, document)
    row, selected = matches[0]
    payable_rule = any(f"header.total.{name}." in (total.rule_id or "") for name in _PAYABLE)
    payable_inline = any(_label(w).casefold() == "payable" for w in row.words)
    if payable_rule or payable_inline:
        proofs = _gross_proofs(rows, row, document)
        # Equality with the balance is irrelevant. Only independent printed gross evidence counts.
        if proofs is not None and len(proofs) == 1:
            return proofs[0]
        return _ambiguous(row.words, "payable_without_unique_gross")
    guarded = guard_total(total, document)
    if guarded.status != ExtractionStatus.AMBIGUOUS or total.rule_id not in {
        "header.total.total.same_line.v1",
        "header.total.total.next_line.v1",
    }:
        return guarded
    separated = _without_reference(row, selected, rows, document)
    if separated is not None and len(_money_spans(separated.words)) == 1:
        return total.model_copy(
            update={
                "evidence": evidence_from_words(separated.words),
                "rule_id": "financial_role.separated_reference.v1",
            }
        )
    return guarded


class FinancialRoleGuardExtractor(DeterministicInvoiceExtractor):
    name = GUARD_NAME
    version = ROLE_GUARD_VERSION

    def extract(self, document: DocumentText) -> Invoice:
        invoice = super().extract(document)
        return invoice.model_copy(update={"total": role_guard_total(invoice.total, document)})
