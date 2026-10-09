"""Opt-in header localization fix; the frozen baseline remains unchanged."""

from datetime import date
from decimal import Decimal

from invoiceops.extraction.evidence import evidence_from_words
from invoiceops.extraction.layout import reconstruct_lines
from invoiceops.extraction.normalization import (
    normalize_identifier,
    parse_invoice_date,
    parse_money,
)
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.schemas.extraction import DocumentText, ExtractedField, ExtractionStatus, Invoice


def _matches(text: str, value: object) -> bool:
    if isinstance(value, date):
        return parse_invoice_date(text) == value
    if isinstance(value, Decimal):
        return parse_money(text) == value
    return normalize_identifier(text) == normalize_identifier(str(value))


def localize_header_value(
    field: ExtractedField[object], document: DocumentText
) -> ExtractedField[object]:
    """Select a unique, smallest source-token span inside existing evidence.

    No annotation data are consulted. Repeated locations and unmatched values
    retain original evidence instead of guessing a location.
    """
    if field.status != ExtractionStatus.EXTRACTED or field.value is None:
        return field
    candidates = {}
    for line in reconstruct_lines(document):
        words = [
            word
            for word in line.words
            if any(
                span.page == word.page
                and span.source == word.source
                and span.bbox.x0 <= word.bbox.x0 + 1e-6
                and span.bbox.y0 <= word.bbox.y0 + 1e-6
                and span.bbox.x1 >= word.bbox.x1 - 1e-6
                and span.bbox.y1 >= word.bbox.y1 - 1e-6
                for span in field.evidence
            )
        ]
        for start in range(len(words)):
            for end in range(start + 1, len(words) + 1):
                selected = words[start:end]
                if not _matches(" ".join(word.text for word in selected), field.value):
                    continue
                evidence = evidence_from_words(selected)
                key = tuple(
                    (span.page, span.bbox.x0, span.bbox.y0, span.bbox.x1, span.bbox.y1)
                    for span in evidence
                )
                candidates[key] = (len(selected), evidence)
    if not candidates:
        return field
    smallest = min(length for length, _ in candidates.values())
    best = [evidence for length, evidence in candidates.values() if length == smallest]
    if len(best) != 1:
        return field
    return field.model_copy(update={"evidence": best[0]})


class ValueGroundedInvoiceExtractor(DeterministicInvoiceExtractor):
    name = "deterministic-value-grounded"
    version = "0.3.0"

    def extract(self, document: DocumentText) -> Invoice:
        invoice = super().extract(document)
        updates = {
            name: localize_header_value(getattr(invoice, name), document)
            for name in ("invoice_number", "invoice_date", "subtotal", "tax", "total")
        }
        return invoice.model_copy(update=updates)
