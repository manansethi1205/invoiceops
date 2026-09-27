import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from invoiceops.db import Base
from invoiceops.jobs.events import append_job_event, event_to_read, list_job_events
from invoiceops.models import Document, IngestionJob
from invoiceops.schemas.jobs import JobEventType


def test_job_events_are_ordered_and_idempotent_by_event_key() -> None:
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        document = Document(
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=12,
            sha256="d" * 64,
            object_key=f"invoices/{uuid.uuid4()}/synthetic.pdf",
        )
        job = IngestionJob(document=document)
        session.add(job)
        session.flush()

        first = append_job_event(
            session,
            job_id=job.id,
            event_key="upload.accepted",
            event_type=JobEventType.UPLOAD_ACCEPTED,
            stage="upload",
            status="completed",
            message="Invoice upload accepted",
        )
        replay = append_job_event(
            session,
            job_id=job.id,
            event_key="upload.accepted",
            event_type=JobEventType.UPLOAD_ACCEPTED,
            stage="upload",
            status="completed",
            message="Invoice upload accepted",
        )
        second = append_job_event(
            session,
            job_id=job.id,
            event_key="document.validated",
            event_type=JobEventType.DOCUMENT_VALIDATED,
            stage="validation",
            status="completed",
            message="Document validated",
        )
        session.commit()

        assert replay.id == first.id
        assert second.sequence_number == 2
        assert [event.sequence_number for event in list_job_events(session, job.id)] == [1, 2]
        resumed = list_job_events(session, job.id, after_sequence=1)
        assert [event.sequence_number for event in resumed] == [2]
        public_event = event_to_read(first)
        assert public_event.sequence == 1
        assert public_event.payload == {}
