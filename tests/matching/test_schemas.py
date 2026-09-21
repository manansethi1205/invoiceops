from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoiceops.schemas.matching import PurchaseOrderCreate


def valid_payload() -> dict[str, object]:
    return {
        "external_po_number": " PO-1 ",
        "vendor_name": " Synthetic Vendor ",
        "currency": "inr",
        "lines": [
            {
                "line_number": "1",
                "description": "Filter",
                "ordered_quantity": "2.500",
                "unit_price": "10.25",
            }
        ],
    }


def test_po_normalizes_strings_and_preserves_decimals() -> None:
    command = PurchaseOrderCreate.model_validate(valid_payload())

    assert command.external_po_number == "PO-1"
    assert command.vendor_name == "Synthetic Vendor"
    assert command.currency == "INR"
    assert command.lines[0].ordered_quantity == Decimal("2.500")
    assert command.model_dump(mode="json")["lines"][0]["unit_price"] == "10.25"


def test_po_rejects_duplicate_line_numbers() -> None:
    payload = valid_payload()
    payload["lines"] = [payload["lines"][0], payload["lines"][0]]  # type: ignore[index]
    with pytest.raises(ValidationError, match="line numbers must be unique"):
        PurchaseOrderCreate.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [("ordered_quantity", 1.5), ("unit_price", 10.25)],
)
def test_po_rejects_float_numeric_inputs(field: str, value: float) -> None:
    payload = valid_payload()
    payload["lines"][0][field] = value  # type: ignore[index]
    with pytest.raises(ValidationError, match="not floats"):
        PurchaseOrderCreate.model_validate(payload)
