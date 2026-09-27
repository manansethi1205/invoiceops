import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from invoiceops.models import IngestionJob, JobEvent
from invoiceops.observability.tracing import trace_identifiers
from invoiceops.schemas.jobs import JobEventRead, JobEventType

TERMINAL_EVENT_TYPES = {
    JobEventType.PROCESSING_COMPLETED,
    JobEventType.PROCESSING_FAILED,
}


def append_job_event(
    session: Session,
    *,
    job_id: uuid.UUID,
    event_key: str,
    event_type: JobEventType,
    stage: str,
    status: str,
    message: str,
    payload: dict[str, object] | None = None,
) -> JobEvent:
    """Append one logical event while holding the job row lock.

    The caller owns the transaction. Reusing an event key returns the existing
    event, making Celery redelivery safe without hiding genuine later stages.
    """
    session.execute(
        select(IngestionJob.id).where(IngestionJob.id == job_id).with_for_update()
    ).scalar_one()
    existing = session.scalar(
        select(JobEvent).where(
            JobEvent.job_id == job_id,
            JobEvent.event_key == event_key,
        )
    )
    if existing is not None:
        return existing
    last_sequence = session.scalar(
        select(func.max(JobEvent.sequence_number)).where(JobEvent.job_id == job_id)
    )
    trace_id, _ = trace_identifiers()
    event = JobEvent(
        job_id=job_id,
        sequence_number=int(last_sequence or 0) + 1,
        event_key=event_key,
        event_type=event_type.value,
        stage=stage,
        status=status,
        message=message,
        payload=payload or {},
        trace_id=trace_id,
        occurred_at=datetime.now(UTC),
    )
    session.add(event)
    session.flush()
    return event


def list_job_events(
    session: Session,
    job_id: uuid.UUID,
    *,
    after_sequence: int = 0,
    limit: int = 50,
) -> list[JobEvent]:
    return list(
        session.scalars(
            select(JobEvent)
            .where(
                JobEvent.job_id == job_id,
                JobEvent.sequence_number > after_sequence,
            )
            .order_by(JobEvent.sequence_number)
            .limit(limit)
        )
    )


def event_to_read(event: JobEvent) -> JobEventRead:
    return JobEventRead(
        id=event.id,
        job_id=event.job_id,
        sequence=event.sequence_number,
        event_type=JobEventType(event.event_type),
        stage=event.stage,
        status=event.status,
        message=event.message,
        occurred_at=event.occurred_at,
        trace_id=event.trace_id,
        payload=event.payload,
    )
