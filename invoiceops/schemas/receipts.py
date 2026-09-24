import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("decimal values must be supplied as strings or integers, not floats")
    return value


def _non_blank(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


class GoodsReceiptLineCreate(BaseModel):
    purchase_order_line_id: uuid.UUID
    accepted_quantity: Decimal = Field(gt=0)

    @field_validator("accepted_quantity", mode="before")
    @classmethod
    def reject_float_quantity(cls, value: object) -> object:
        return _reject_float(value)


class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purchase_order_id: uuid.UUID
    external_receipt_number: str
    received_at: datetime
    lines: list[GoodsReceiptLineCreate] = Field(min_length=1)

    @field_validator("external_receipt_number")
    @classmethod
    def receipt_number_nonblank(cls, value: str) -> str:
        return _non_blank(value)

    @field_validator("received_at")
    @classmethod
    def received_at_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def receipt_lines_unique(self) -> "GoodsReceiptCreate":
        line_ids = [line.purchase_order_line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("a purchase-order line may appear only once in a receipt")
        return self


class GoodsReceiptLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    purchase_order_line_id: uuid.UUID
    accepted_quantity: Decimal


class GoodsReceiptReversalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_id: str
    reason: str
    reversed_at: datetime


class GoodsReceiptRead(BaseModel):
    id: uuid.UUID
    purchase_order_id: uuid.UUID
    external_receipt_number: str
    received_at: datetime
    request_fingerprint: str
    created_at: datetime
    lines: list[GoodsReceiptLineRead]
    reversal: GoodsReceiptReversalRead | None


class ReverseGoodsReceiptCommand(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_nonblank(cls, value: str) -> str:
        return _non_blank(value)
