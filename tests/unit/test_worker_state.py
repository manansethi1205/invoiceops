import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from invoiceops.db import Base
from invoiceops.models import Document, IngestionJob, JobStatus
from workers.extraction.tasks import record_failure, run_job


def make_session() -> Session:
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def create_job(session: Session) -> IngestionJob:
    document = Document(
        original_filename="synthetic.pdf",
        content_type="application/pdf",
        byte_size=14,
        sha256="a" * 64,
        object_key=f"invoices/{uuid.uuid4()}/synthetic.pdf",
    )
    job = IngestionJob(document=document)
    session.add(job)
    session.commit()
    return job


def test_failed_attempt_can_retry_and_completed_redelivery_is_noop() -> None:
    with make_session() as session:
        job = create_job(session)

        def transient_failure(_document: Document) -> None:
            raise RuntimeError("synthetic transient failure")

        with pytest.raises(RuntimeError, match="synthetic transient failure"):
            run_job(session, job.id, transient_failure)
        session.refresh(job)
        assert job.status == JobStatus.PROCESSING

        record_failure(session, job.id, terminal=False)
        session.refresh(job)
        assert job.status == JobStatus.QUEUED
        assert job.error_code is None

        calls: list[uuid.UUID] = []
        assert run_job(session, job.id, lambda document: calls.append(document.id)) is True
        session.refresh(job)
        assert job.status == JobStatus.SUCCEEDED
        assert calls == [job.document_id]

        assert run_job(session, job.id, lambda document: calls.append(document.id)) is False
        assert calls == [job.document_id]


def test_terminal_failure_is_visible_in_job_status() -> None:
    with make_session() as session:
        job = create_job(session)
        record_failure(session, job.id, terminal=True)
        session.refresh(job)
        assert job.status == JobStatus.FAILED
        assert job.error_code == "processing_failed"
        assert job.error_message == "Document processing failed"

