import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from invoiceops.models import CaseEvent, PayableCase
from invoiceops.schemas.cases import CaseEventRead, DocumentRole


def append_case_event(
    session: Session,
    *,
    case_id: uuid.UUID,
    event_key: str,
    event_type: str,
    stage: str,
    status: str,
    message: str,
    document_id: uuid.UUID | None = None,
    document_role: DocumentRole | None = None,
    payload: dict[str, object] | None = None,
) -> CaseEvent:
    session.execute(
        select(PayableCase.id).where(PayableCase.id == case_id).with_for_update()
    ).scalar_one()
    existing = session.scalar(
        select(CaseEvent).where(CaseEvent.case_id == case_id, CaseEvent.event_key == event_key)
    )
    if existing is not None:
        return existing
    last_sequence = session.scalar(
        select(func.max(CaseEvent.sequence_number)).where(CaseEvent.case_id == case_id)
    )
    event = CaseEvent(
        case_id=case_id,
        sequence_number=int(last_sequence or 0) + 1,
        event_key=event_key,
        event_type=event_type,
        stage=stage,
        status=status,
        message=message,
        document_id=document_id,
        document_role=document_role,
        payload=payload or {},
        occurred_at=datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    return event


def event_to_read(event: CaseEvent) -> CaseEventRead:
    return CaseEventRead(
        id=event.id,
        case_id=event.case_id,
        sequence=event.sequence_number,
        event_type=event.event_type,
        stage=event.stage,
        status=event.status,
        message=event.message,
        document_id=event.document_id,
        document_role=event.document_role,
        payload=event.payload,
        occurred_at=event.occurred_at,
    )
