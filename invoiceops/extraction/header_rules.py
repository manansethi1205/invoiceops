import re
from datetime import date
from decimal import Decimal

from invoiceops.extraction.candidates import FieldCandidate, resolve_candidates
from invoiceops.extraction.layout import TextLine, union_bbox
from invoiceops.extraction.normalization import (
    normalize_currency,
    normalize_identifier,
    normalize_whitespace,
    parse_invoice_date,
    parse_money,
)
from invoiceops.schemas.extraction import EvidenceSpan, ExtractedField, TextSource, WordToken

_INVOICE_NUMBER_LABEL = re.compile(
    r"\b(?:invoice\s*(?:number|no\.?|#)|inv\.?\s*(?:number|no\.?|#)|"
    r"bill\s*(?:number|no\.?|#))\b",
    re.IGNORECASE,
)
_INVOICE_DATE_LABEL = re.compile(
    r"\b(?:invoice date|bill date|issue date|date of issue)\b", re.IGNORECASE
)
_EXCLUDED_DATE_LABEL = re.compile(r"\b(?:due|delivery|po)\s+date\b", re.IGNORECASE)
_GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$", re.IGNORECASE)
_PAGE_NUMBER = re.compile(r"^(?:page\s*)?\d+(?:\s+of\s+\d+)?$", re.IGNORECASE)
_MONEY_FRAGMENT = re.compile(
    r"(?:\(\s*)?(?:(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD|RS\.?)\s*|[₹€£$]\s*)?"
    r"[+-]?\d[\d ,.]*?(?:\s*\))?(?=\s*(?:$|[|;]))",
    re.IGNORECASE,
)
_ISO_CODE = re.compile(r"\b(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD)\b", re.IGNORECASE)
_CURRENCY_NAME = re.compile(
    r"\b(?:Indian rupees?|rupees?|euros?|pound sterling|dirhams?)\b", re.IGNORECASE
)
_CURRENCY_CONTEXT = re.compile(
    r"\b(?:currency|amount due|grand total|total payable|invoice total|net payable|"
    r"sub\s*total|tax|GST|IGST|CGST|SGST|total)\b",
    re.IGNORECASE,
)


def _line_evidence(line: TextLine) -> list[EvidenceSpan]:
    by_source: dict[TextSource, list[WordToken]] = {}
    for word in line.words:
        by_source.setdefault(word.source, []).append(word)
    return [
        EvidenceSpan(
            page=line.page,
            bbox=union_bbox(words),
            text=" ".join(word.text for word in words),
            source=source,
        )
        for source, words in by_source.items()
    ]


def _remainder(line: TextLine, match: re.Match[str]) -> str:
    return normalize_whitespace(line.text[match.end() :].lstrip(" :#.-"))


def _next_line(lines: list[TextLine], index: int) -> TextLine | None:
    if index + 1 >= len(lines) or lines[index + 1].page != lines[index].page:
        return None
    return lines[index + 1]


def _valid_identifier(value: str) -> bool:
    normalized = normalize_identifier(value)
    if not normalized or len(normalized) < 2:
        return False
    if parse_invoice_date(value) is not None or parse_money(value) is not None:
        return False
    if _GSTIN.fullmatch(normalized) or _PAGE_NUMBER.fullmatch(value.strip()):
        return False
    if re.match(r"^(?:PO|PURCHASEORDER)", normalized):
        return False
    return True


def extract_invoice_number(lines: list[TextLine]) -> ExtractedField[str]:
    candidates: list[FieldCandidate[str]] = []
    for index, line in enumerate(lines):
        match = _INVOICE_NUMBER_LABEL.search(line.text)
        if match is None:
            continue
        value = _remainder(line, match)
        if value and _valid_identifier(value):
            candidates.append(
                FieldCandidate(
                    value=value,
                    evidence=_line_evidence(line),
                    rule_id="header.invoice_number.same_line.v1",
                    priority=100,
                )
            )
            continue
        following = _next_line(lines, index)
        if following is not None:
            value = normalize_whitespace(following.text)
            if _valid_identifier(value):
                candidates.append(
                    FieldCandidate(
                        value=value,
                        evidence=_line_evidence(line) + _line_evidence(following),
                        rule_id="header.invoice_number.next_line.v1",
                        priority=90,
                    )
                )
    return resolve_candidates(
        candidates,
        comparison_key=normalize_identifier,
        ambiguous_rule_id="header.invoice_number.ambiguous.v1",
    )


def extract_invoice_date(lines: list[TextLine]) -> ExtractedField[date]:
    candidates: list[FieldCandidate[date]] = []
    for index, line in enumerate(lines):
        if _EXCLUDED_DATE_LABEL.search(line.text):
            continue
        match = _INVOICE_DATE_LABEL.search(line.text)
        if match is None:
            continue
        value = parse_invoice_date(_remainder(line, match))
        if value is not None:
            candidates.append(
                FieldCandidate(
                    value=value,
                    evidence=_line_evidence(line),
                    rule_id="header.invoice_date.same_line.v1",
                    priority=100,
                )
            )
            continue
        following = _next_line(lines, index)
        if following is not None:
            value = parse_invoice_date(following.text)
            if value is not None:
                candidates.append(
                    FieldCandidate(
                        value=value,
                        evidence=_line_evidence(line) + _line_evidence(following),
                        rule_id="header.invoice_date.next_line.v1",
                        priority=90,
                    )
                )
    return resolve_candidates(
        candidates,
        comparison_key=lambda value: value,
        ambiguous_rule_id="header.invoice_date.ambiguous.v1",
    )


def _money_from_text(value: str) -> Decimal | None:
    matches = list(_MONEY_FRAGMENT.finditer(value.strip()))
    for match in reversed(matches):
        amount = parse_money(match.group())
        if amount is not None:
            return amount
    return None


def _extract_labeled_money(
    lines: list[TextLine],
    *,
    field_name: str,
    labels: list[tuple[str, re.Pattern[str], int]],
    exclusions: re.Pattern[str] | None = None,
) -> ExtractedField[Decimal]:
    candidates: list[FieldCandidate[Decimal]] = []
    for index, line in enumerate(lines):
        if exclusions is not None and exclusions.search(line.text):
            continue
        for label_name, pattern, priority in labels:
            match = pattern.search(line.text)
            if match is None:
                continue
            amount = _money_from_text(line.text[match.end() :])
            if amount is not None:
                candidates.append(
                    FieldCandidate(
                        value=amount,
                        evidence=_line_evidence(line),
                        rule_id=f"header.{field_name}.{label_name}.same_line.v1",
                        priority=priority,
                    )
                )
            else:
                following = _next_line(lines, index)
                if following is not None:
                    amount = _money_from_text(following.text)
                    if amount is not None:
                        candidates.append(
                            FieldCandidate(
                                value=amount,
                                evidence=_line_evidence(line) + _line_evidence(following),
                                rule_id=f"header.{field_name}.{label_name}.next_line.v1",
                                priority=priority - 1,
                            )
                        )
            break
    return resolve_candidates(
        candidates,
        comparison_key=lambda value: value,
        ambiguous_rule_id=f"header.{field_name}.ambiguous.v1",
    )


def extract_subtotal(lines: list[TextLine]) -> ExtractedField[Decimal]:
    return _extract_labeled_money(
        lines,
        field_name="subtotal",
        labels=[
            ("subtotal", re.compile(r"^\s*sub\s*total\b", re.IGNORECASE), 90),
            ("taxable_amount", re.compile(r"^\s*taxable amount\b", re.IGNORECASE), 80),
        ],
    )


def extract_tax(lines: list[TextLine]) -> ExtractedField[Decimal]:
    return _extract_labeled_money(
        lines,
        field_name="tax",
        labels=[
            ("tax_total", re.compile(r"^\s*(?:tax total|total tax)\b", re.IGNORECASE), 95),
            ("gst", re.compile(r"^\s*(?:GST|IGST)\b", re.IGNORECASE), 90),
            ("split_gst", re.compile(r"^\s*(?:CGST|SGST)\b", re.IGNORECASE), 85),
        ],
    )


def extract_total(lines: list[TextLine]) -> ExtractedField[Decimal]:
    return _extract_labeled_money(
        lines,
        field_name="total",
        labels=[
            ("amount_due", re.compile(r"^\s*amount due\b", re.IGNORECASE), 100),
            ("grand_total", re.compile(r"^\s*grand total\b", re.IGNORECASE), 95),
            ("total_payable", re.compile(r"^\s*total payable\b", re.IGNORECASE), 90),
            ("invoice_total", re.compile(r"^\s*invoice total\b", re.IGNORECASE), 85),
            ("net_payable", re.compile(r"^\s*net payable\b", re.IGNORECASE), 80),
            ("total", re.compile(r"^\s*total\b", re.IGNORECASE), 50),
        ],
        exclusions=re.compile(
            r"^\s*(?:sub\s*total|tax total|total tax|quantity total|discount total)\b",
            re.IGNORECASE,
        ),
    )


def extract_currency(lines: list[TextLine]) -> ExtractedField[str]:
    candidates: list[FieldCandidate[str]] = []
    for index, line in enumerate(lines):
        has_currency_context = _CURRENCY_CONTEXT.search(line.text) is not None
        label = re.search(r"\bcurrency\b\s*[:#.-]?\s*(.*)$", line.text, re.IGNORECASE)
        if label is not None:
            code_match = _ISO_CODE.search(label.group(1))
            if code_match is not None:
                value = normalize_currency(code_match.group())
                if value is not None:
                    candidates.append(
                        FieldCandidate(
                            value=value,
                            evidence=_line_evidence(line),
                            rule_id="header.currency.label_iso.v1",
                            priority=120,
                        )
                    )
            elif not label.group(1).strip():
                following = _next_line(lines, index)
                if following is not None:
                    value = normalize_currency(following.text)
                    if value is not None:
                        candidates.append(
                            FieldCandidate(
                                value=value,
                                evidence=_line_evidence(line) + _line_evidence(following),
                                rule_id="header.currency.label.next_line.v1",
                                priority=119,
                            )
                        )
        for match in _ISO_CODE.finditer(line.text) if has_currency_context else ():
            value = normalize_currency(match.group())
            if value is not None:
                candidates.append(
                    FieldCandidate(
                        value=value,
                        evidence=_line_evidence(line),
                        rule_id="header.currency.iso_code.v1",
                        priority=100,
                    )
                )
        for match in _CURRENCY_NAME.finditer(line.text) if has_currency_context else ():
            value = normalize_currency(match.group())
            if value is not None:
                candidates.append(
                    FieldCandidate(
                        value=value,
                        evidence=_line_evidence(line),
                        rule_id="header.currency.name.v1",
                        priority=80,
                    )
                )
        for symbol in ("₹", "€", "£"):
            if has_currency_context and re.search(rf"{re.escape(symbol)}\s*\d", line.text):
                value = normalize_currency(symbol)
                if value is not None:
                    candidates.append(
                        FieldCandidate(
                            value=value,
                            evidence=_line_evidence(line),
                            rule_id="header.currency.symbol.v1",
                            priority=60,
                        )
                    )
    return resolve_candidates(
        candidates,
        comparison_key=lambda value: value,
        ambiguous_rule_id="header.currency.ambiguous.v1",
    )
