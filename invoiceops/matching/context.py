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
        current_document_id: uuid.UUID | None = None,
    ) -> tuple[ThreeWayContextSnapshot, str, str]:
        receipts = list(
            self.session.scalars(
                select(GoodsReceipt)
                .where(GoodsReceipt.purchase_order_id == purchase_order.id)
                .options(selectinload(GoodsReceipt.lines), selectinload(GoodsReceipt.reversal))
                .order_by(GoodsReceipt.received_at, GoodsReceipt.id)
            )
        )
        allocations = list(
            self.session.scalars(
                select(ThreeWayAllocation)
                .where(ThreeWayAllocation.purchase_order_id == purchase_order.id)
                .order_by(ThreeWayAllocation.created_at, ThreeWayAllocation.id)
            )
        )
        allocations = sorted(allocations, key=lambda item: str(item.id))
        current_allocations = [
            item for item in allocations if item.document_id == current_document_id
        ]
        prior_allocations = [
            item for item in allocations if item.document_id != current_document_id
        ]
        prior_by_line: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        for allocation in prior_allocations:
            prior_by_line[allocation.purchase_order_line_id] += allocation.allocated_quantity

        def allocation_read(item: ThreeWayAllocation) -> PriorAllocationRead:
            return PriorAllocationRead(
                allocation_id=item.id,
                match_run_id=item.match_run_id,
                document_id=item.document_id,
                extraction_run_id=item.extraction_run_id,
                purchase_order_id=item.purchase_order_id,
                purchase_order_line_id=item.purchase_order_line_id,
                invoice_line_index=item.invoice_line_index,
                allocated_quantity=decimal_text(item.allocated_quantity),
            )

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
                        allocation_read(item)
                        for item in prior_allocations
                        if item.purchase_order_line_id == po_line.id
                    ],
                    current_invoice_allocations=[
                        allocation_read(item)
                        for item in current_allocations
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
            "context_version": "three-way-context-v2",
            "snapshot": snapshot.model_dump(mode="json"),
            "prior_allocation_ids": [str(item.id) for item in prior_allocations],
            "current_invoice_allocation_ids": [
                str(item.id) for item in current_allocations
            ],
            "policy": policy.model_dump(mode="json"),
        }
        canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
        replay_lines: list[dict[str, object]] = []
        for line in snapshot.model_dump(mode="json")["lines"]:
            assert isinstance(line, dict)
            replay_line = dict(line)
            replay_line.pop("current_invoice_allocations", None)
            replay_prior = replay_line["prior_allocations"]
            assert isinstance(replay_prior, list)
            replay_line["prior_allocations"] = [
                {
                    "allocation_id": item["allocation_id"],
                    "match_run_id": item["match_run_id"],
                    "allocated_quantity": item["allocated_quantity"],
                }
                for item in replay_prior
                if isinstance(item, dict)
            ]
            replay_lines.append(replay_line)
        replay_snapshot = {
            "purchase_order_id": str(snapshot.purchase_order_id),
            "policy_version": snapshot.policy_version,
            "lines": replay_lines,
        }
        replay_envelope = {
            "context_version": "three-way-context-v1",
            "snapshot": replay_snapshot,
            "allocation_ids": [str(item.id) for item in prior_allocations],
            "policy": policy.model_dump(mode="json"),
        }
        replay_canonical = json.dumps(
            replay_envelope, sort_keys=True, separators=(",", ":")
        ).encode()
        return (
            snapshot,
            hashlib.sha256(canonical).hexdigest(),
            hashlib.sha256(replay_canonical).hexdigest(),
        )
