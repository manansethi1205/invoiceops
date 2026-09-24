import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptReversal,
)
from invoiceops.po_locking import lock_purchase_order
from invoiceops.schemas.receipts import GoodsReceiptCreate, GoodsReceiptRead


class GoodsReceiptNotFoundError(LookupError):
    pass


class ReceiptPurchaseOrderNotFoundError(LookupError):
    pass


class ReceiptLineNotFoundError(LookupError):
    pass


class ConflictingReceiptReplayError(RuntimeError):
    pass


class GoodsReceiptAlreadyReversedError(RuntimeError):
    pass


@dataclass(frozen=True)
class GoodsReceiptServiceResult:
    receipt: GoodsReceipt
    created: bool


def _canonical_timestamp(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def receipt_request_fingerprint(command: GoodsReceiptCreate) -> str:
    envelope = {
        "purchase_order_id": str(command.purchase_order_id),
        "external_receipt_number": command.external_receipt_number,
        "received_at": _canonical_timestamp(command.received_at),
        "lines": sorted(
            (
                {
                    "purchase_order_line_id": str(line.purchase_order_line_id),
                    "accepted_quantity": format(line.accepted_quantity, "f"),
                }
                for line in command.lines
            ),
            key=lambda item: item["purchase_order_line_id"],
        ),
    }
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def goods_receipt_to_read(receipt: GoodsReceipt) -> GoodsReceiptRead:
    return GoodsReceiptRead.model_validate(receipt, from_attributes=True)


class GoodsReceiptService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, command: GoodsReceiptCreate) -> GoodsReceiptServiceResult:
        purchase_order = lock_purchase_order(
            self.session, command.purchase_order_id, include_lines=True
        )
        if purchase_order is None:
            raise ReceiptPurchaseOrderNotFoundError
        line_ids = {line.purchase_order_line_id for line in command.lines}
        found = {line.id for line in purchase_order.lines if line.id in line_ids}
        if found != line_ids:
            raise ReceiptLineNotFoundError
        fingerprint = receipt_request_fingerprint(command)
        existing = self._find_by_business_key(
            command.purchase_order_id, command.external_receipt_number
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise ConflictingReceiptReplayError
            return GoodsReceiptServiceResult(existing, False)
        receipt = GoodsReceipt(
            purchase_order_id=command.purchase_order_id,
            external_receipt_number=command.external_receipt_number,
            received_at=command.received_at,
            request_fingerprint=fingerprint,
            lines=[
                GoodsReceiptLine(
                    purchase_order_line_id=line.purchase_order_line_id,
                    accepted_quantity=line.accepted_quantity,
                )
                for line in command.lines
            ],
        )
        self.session.add(receipt)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_by_business_key(
                command.purchase_order_id, command.external_receipt_number
            )
            if concurrent is None or concurrent.request_fingerprint != fingerprint:
                raise ConflictingReceiptReplayError from None
            return GoodsReceiptServiceResult(concurrent, False)
        self.session.expire_all()
        return GoodsReceiptServiceResult(self.get(receipt.id), True)

    def get(self, receipt_id: uuid.UUID) -> GoodsReceipt:
        receipt = self.session.scalar(
            select(GoodsReceipt)
            .where(GoodsReceipt.id == receipt_id)
            .options(selectinload(GoodsReceipt.lines), selectinload(GoodsReceipt.reversal))
        )
        if receipt is None:
            raise GoodsReceiptNotFoundError
        return receipt

    def list(self, purchase_order_id: uuid.UUID | None = None) -> list[GoodsReceipt]:
        query = select(GoodsReceipt).options(
            selectinload(GoodsReceipt.lines), selectinload(GoodsReceipt.reversal)
        )
        if purchase_order_id is not None:
            query = query.where(GoodsReceipt.purchase_order_id == purchase_order_id)
        return list(self.session.scalars(query.order_by(GoodsReceipt.created_at, GoodsReceipt.id)))

    def reverse(self, receipt_id: uuid.UUID, actor_id: str, reason: str) -> GoodsReceipt:
        purchase_order_id = self.session.scalar(
            select(GoodsReceipt.purchase_order_id).where(GoodsReceipt.id == receipt_id)
        )
        if purchase_order_id is None:
            raise GoodsReceiptNotFoundError
        if lock_purchase_order(self.session, purchase_order_id) is None:
            raise ReceiptPurchaseOrderNotFoundError
        receipt = self.get(receipt_id)
        if receipt.reversal is not None:
            raise GoodsReceiptAlreadyReversedError
        self.session.add(
            GoodsReceiptReversal(
                goods_receipt_id=receipt.id,
                actor_id=actor_id,
                reason=reason,
                reversed_at=datetime.now(UTC),
            )
        )
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise GoodsReceiptAlreadyReversedError from exc
        return self.get(receipt_id)

    def _find_by_business_key(
        self, purchase_order_id: uuid.UUID, external_receipt_number: str
    ) -> GoodsReceipt | None:
        return self.session.scalar(
            select(GoodsReceipt)
            .where(
                GoodsReceipt.purchase_order_id == purchase_order_id,
                GoodsReceipt.external_receipt_number == external_receipt_number,
            )
            .options(selectinload(GoodsReceipt.lines), selectinload(GoodsReceipt.reversal))
        )
