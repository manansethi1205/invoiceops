import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import GoodsReceipt, PurchaseOrder, ThreeWayAllocation
from invoiceops.schemas.matching import ThreeWayMatchingPolicy
from invoiceops.schemas.three_way import (
    PriorAllocationRead,
    ReceiptLineContextRead,
    ReceiptQuantityRead,
    ThreeWayContextSnapshot,
)


def decimal_text(value: Decimal) -> str:
    return format(value, "f")


class ThreeWayContextBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build(
        self,
        purchase_order: PurchaseOrder,
        policy: ThreeWayMatchingPolicy,
        *,
        exclude_match_run_id: uuid.UUID | None = None,
    ) -> tuple[ThreeWayContextSnapshot, str]:
        receipts = list(
            self.session.scalars(
                select(GoodsReceipt)
                .where(GoodsReceipt.purchase_order_id == purchase_order.id)
                .options(selectinload(GoodsReceipt.lines), selectinload(GoodsReceipt.reversal))
                .order_by(GoodsReceipt.received_at, GoodsReceipt.id)
            )
        )
        line_ids = [line.id for line in purchase_order.lines]
        allocation_query = select(ThreeWayAllocation).where(
            ThreeWayAllocation.purchase_order_line_id.in_(line_ids)
        )
        if exclude_match_run_id is not None:
            allocation_query = allocation_query.where(
                ThreeWayAllocation.match_run_id != exclude_match_run_id
            )
        allocations = list(
            self.session.scalars(
                allocation_query.order_by(ThreeWayAllocation.created_at, ThreeWayAllocation.id)
            )
        )
        allocations = sorted(allocations, key=lambda item: str(item.id))
        prior_by_line: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        for allocation in allocations:
            prior_by_line[allocation.purchase_order_line_id] += allocation.allocated_quantity

        contexts: list[ReceiptLineContextRead] = []
        for po_line in purchase_order.lines:
            active: list[ReceiptQuantityRead] = []
            reversed_receipts: list[ReceiptQuantityRead] = []
            reversal_ids: list[uuid.UUID] = []
            for receipt in receipts:
                receipt_line = next(
                    (item for item in receipt.lines if item.purchase_order_line_id == po_line.id),
                    None,
                )
                if receipt_line is None:
                    continue
                if receipt.reversal is not None:
                    reversed_receipts.append(
                        ReceiptQuantityRead(
                            receipt_id=receipt.id,
                            accepted_quantity=decimal_text(receipt_line.accepted_quantity),
                            received_at=receipt.received_at,
                        )
                    )
                    reversal_ids.append(receipt.reversal.id)
                else:
                    active.append(
                        ReceiptQuantityRead(
                            receipt_id=receipt.id,
                            accepted_quantity=decimal_text(receipt_line.accepted_quantity),
                            received_at=receipt.received_at,
                        )
                    )
            received = sum((Decimal(item.accepted_quantity) for item in active), Decimal("0"))
            prior = prior_by_line[po_line.id]
            contexts.append(
                ReceiptLineContextRead(
                    purchase_order_line_id=po_line.id,
                    ordered_quantity=decimal_text(po_line.ordered_quantity),
                    active_receipts=sorted(active, key=lambda item: str(item.receipt_id)),
                    reversed_receipts=sorted(
                        reversed_receipts, key=lambda item: str(item.receipt_id)
                    ),
                    reversal_ids=sorted(reversal_ids, key=str),
                    prior_allocations=[
                        PriorAllocationRead(
                            allocation_id=item.id,
                            match_run_id=item.match_run_id,
                            allocated_quantity=decimal_text(item.allocated_quantity),
                        )
                        for item in allocations
                        if item.purchase_order_line_id == po_line.id
                    ],
                    effective_received_quantity=decimal_text(received),
                    previously_allocated_quantity=decimal_text(prior),
                    available_quantity=decimal_text(received - prior),
                )
            )
        snapshot = ThreeWayContextSnapshot(
            purchase_order_id=purchase_order.id,
            policy_version=policy.version,
            lines=contexts,
        )
        envelope = {
            "context_version": "three-way-context-v1",
            "snapshot": snapshot.model_dump(mode="json"),
            "allocation_ids": [str(item.id) for item in allocations],
            "policy": policy.model_dump(mode="json"),
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        return snapshot, hashlib.sha256(canonical).hexdigest()
