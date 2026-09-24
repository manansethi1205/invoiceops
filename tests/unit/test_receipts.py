import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from invoiceops.receipts.service import receipt_request_fingerprint
from invoiceops.schemas.receipts import GoodsReceiptCreate


def _payload() -> dict[str, object]:
    return {
        "purchase_order_id": str(uuid.uuid4()),
        "external_receipt_number": "GRN-SYN-1",
        "received_at": "2026-09-20T12:00:00Z",
        "lines": [
            {
                "purchase_order_line_id": str(uuid.uuid4()),
                "accepted_quantity": "2.5",
            }
        ],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("external_receipt_number", " "),
        ("lines", []),
    ],
)
def test_receipt_rejects_invalid_required_values(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError):
        GoodsReceiptCreate.model_validate(payload)


def test_receipt_rejects_float_nonpositive_and_duplicate_line_quantities() -> None:
    for quantity in (1.5, "0", "-1"):
        payload = _payload()
        payload["lines"][0]["accepted_quantity"] = quantity  # type: ignore[index]
        with pytest.raises(ValidationError):
            GoodsReceiptCreate.model_validate(payload)
    payload = _payload()
    payload["lines"] = [payload["lines"][0], payload["lines"][0]]  # type: ignore[index]
    with pytest.raises(ValidationError):
        GoodsReceiptCreate.model_validate(payload)

    payload = _payload()
    payload["received_at"] = "2026-09-20T12:00:00"
    with pytest.raises(ValidationError):
        GoodsReceiptCreate.model_validate(payload)


def test_receipt_fingerprint_is_stable_for_line_order_and_equivalent_timezones() -> None:
    first = _payload()
    second_line = {
        "purchase_order_line_id": str(uuid.uuid4()),
        "accepted_quantity": "1.00",
    }
    first["lines"].append(second_line)  # type: ignore[union-attr]
    second = dict(first)
    second["lines"] = list(reversed(first["lines"]))  # type: ignore[arg-type]
    second["received_at"] = datetime(
        2026, 9, 20, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    first["received_at"] = datetime(2026, 9, 20, 12, tzinfo=UTC)
    assert receipt_request_fingerprint(
        GoodsReceiptCreate.model_validate(first)
    ) == receipt_request_fingerprint(GoodsReceiptCreate.model_validate(second))
