import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReceiptQuantityRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: uuid.UUID
    accepted_quantity: str
    received_at: datetime


class PriorAllocationRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    allocation_id: uuid.UUID
    match_run_id: uuid.UUID
    allocated_quantity: str


class ReceiptLineContextRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    purchase_order_line_id: uuid.UUID
    ordered_quantity: str
    active_receipts: list[ReceiptQuantityRead]
    reversed_receipts: list[ReceiptQuantityRead] = Field(default_factory=list)
    reversal_ids: list[uuid.UUID] = Field(default_factory=list)
    prior_allocations: list[PriorAllocationRead] = Field(default_factory=list)
    effective_received_quantity: str
    previously_allocated_quantity: str
    available_quantity: str

    @property
    def reversed_receipt_ids(self) -> list[uuid.UUID]:
        return [item.receipt_id for item in self.reversed_receipts]


class ThreeWayContextSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    purchase_order_id: uuid.UUID
    policy_version: str
    lines: list[ReceiptLineContextRead]


class ThreeWayContextRead(BaseModel):
    match_run_id: uuid.UUID
    context_fingerprint: str
    snapshot: ThreeWayContextSnapshot
    created_at: datetime
