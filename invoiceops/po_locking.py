import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from invoiceops.models import PurchaseOrder


def lock_purchase_order(
    session: Session,
    purchase_order_id: uuid.UUID,
    *,
    include_lines: bool = False,
) -> PurchaseOrder | None:
    """Acquire the shared PO mutation lock used by receipts and matching."""
    query = select(PurchaseOrder).where(PurchaseOrder.id == purchase_order_id).with_for_update()
    if include_lines:
        query = query.options(selectinload(PurchaseOrder.lines))
    return session.scalar(query)
