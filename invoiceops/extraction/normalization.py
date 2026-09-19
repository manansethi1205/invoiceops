import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from invoiceops.schemas.extraction import BoundingBox

_CURRENCY_CODES = {"AED", "AUD", "CAD", "CHF", "EUR", "GBP", "INR", "JPY", "SGD", "USD"}
_CURRENCY_NAMES = {
    "DIRHAM": "AED",
    "DIRHAMS": "AED",
    "EURO": "EUR",
    "EUROS": "EUR",
    "INDIAN RUPEE": "INR",
    "INDIAN RUPEES": "INR",
    "POUND STERLING": "GBP",
    "RUPEE": "INR",
    "RUPEES": "INR",
}
_CURRENCY_SYMBOLS = {"₹": "INR", "€": "EUR", "£": "GBP"}


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def parse_invoice_date(value: str) -> date | None:
    normalized = normalize_whitespace(value.strip(" :"))
    for date_format in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    return None


def parse_money(value: str) -> Decimal | None:
    normalized = normalize_whitespace(value).replace("\u00a0", " ").strip()
    negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
    if negative_parentheses:
        normalized = normalized[1:-1].strip()

    normalized = re.sub(
        r"(?i)^(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD|RS\.?|RUPEES?)\s*",
        "",
        normalized,
    )
    normalized = re.sub(
        r"(?i)\s*(?:AED|AUD|CAD|CHF|EUR|GBP|INR|JPY|SGD|USD|RS\.?|RUPEES?)$",
        "",
        normalized,
    )
    normalized = normalized.lstrip("₹€£$").strip()
    if not normalized or not re.fullmatch(r"[+-]?[0-9][0-9 ,.]*", normalized):
        return None

    explicit_negative = normalized.startswith("-")
    normalized = normalized.lstrip("+-").replace(" ", "")
    if "," in normalized and "." in normalized:
        if normalized.rfind(",") > normalized.rfind("."):
            normalized = normalized.replace(".", "").replace(",", ".")
        else:
            normalized = normalized.replace(",", "")
    elif "," in normalized:
        comma_parts = normalized.split(",")
        if len(comma_parts) == 2 and len(comma_parts[1]) in {1, 2}:
            normalized = ".".join(comma_parts)
        elif all(len(part) == 3 for part in comma_parts[1:]):
            normalized = "".join(comma_parts)
        else:
            return None
    elif normalized.count(".") > 1:
        dot_parts = normalized.split(".")
        if all(len(part) == 3 for part in dot_parts[1:]):
            normalized = "".join(dot_parts)
        else:
            return None

    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", normalized):
        return None
    try:
        amount = Decimal(normalized)
    except InvalidOperation:
        return None
    if negative_parentheses or explicit_negative:
        amount = -amount
    return amount


def normalize_currency(value: str) -> str | None:
    normalized = normalize_whitespace(value).strip(" .:").upper()
    if normalized in _CURRENCY_CODES:
        return normalized
    if normalized in _CURRENCY_NAMES:
        return _CURRENCY_NAMES[normalized]
    return _CURRENCY_SYMBOLS.get(value.strip())


def normalize_bbox(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    *,
    page_x0: float,
    page_y0: float,
    page_width: float,
    page_height: float,
) -> BoundingBox:
    if page_width <= 0 or page_height <= 0:
        raise ValueError("page dimensions must be positive")

    def clamp(value: float) -> float:
        return min(1.0, max(0.0, value))

    return BoundingBox(
        x0=clamp((x0 - page_x0) / page_width),
        y0=clamp((y0 - page_y0) / page_height),
        x1=clamp((x1 - page_x0) / page_width),
        y1=clamp((y1 - page_y0) / page_height),
    )
