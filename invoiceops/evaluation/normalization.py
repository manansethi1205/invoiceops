import re
from datetime import date
from decimal import Decimal

from invoiceops.extraction.normalization import normalize_identifier, normalize_whitespace


def normalize_description(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_whitespace(value).casefold()).strip()


def canonical_value(value: object | None, field_name: str) -> str | None:
    if value is None:
        return None
    if field_name == "invoice_number":
        return normalize_identifier(str(value))
    if field_name == "description":
        return normalize_description(str(value))
    if field_name == "currency":
        return str(value).upper()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return normalize_whitespace(str(value))
