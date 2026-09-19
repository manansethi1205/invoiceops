import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from invoiceops.db import Base
from invoiceops.extraction.errors import UnreadableDocumentError
from invoiceops.models import Document, IngestionJob, JobStatus
from workers.extraction import tasks
from workers.extraction.tasks import process_document, record_failure, run_job


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


def task_session_factory() -> tuple[sessionmaker[Session], uuid.UUID]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        job_id = create_job(session).id
    return factory, job_id


def test_terminal_document_failure_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, job_id = task_session_factory()
    retry_calls = 0

    class TerminalService:
        def process(self, _document: Document) -> object:
            raise UnreadableDocumentError("raw document text must not be persisted")

    def forbidden_retry(*_args: object, **_kwargs: object) -> object:
        nonlocal retry_calls
        retry_calls += 1
        raise AssertionError("terminal extraction errors must not be retried")

    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setattr(tasks, "build_extraction_service", lambda _session: TerminalService())
    monkeypatch.setattr(process_document, "retry", forbidden_retry)

    with pytest.raises(UnreadableDocumentError):
        process_document.run(str(job_id))

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.error_code == "document_unreadable"
        assert job.error_message == "The document could not be read"
        assert "raw document" not in job.error_message
    assert retry_calls == 0


def test_operational_failure_requeues_and_requests_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    factory, job_id = task_session_factory()

    class RetryRequested(Exception):
        pass

    class OperationalFailureService:
        def process(self, _document: Document) -> object:
            raise ConnectionError("temporary object-storage failure")

    def request_retry(*_args: object, **_kwargs: object) -> Exception:
        return RetryRequested()

    monkeypatch.setattr(tasks, "SessionLocal", factory)
    monkeypatch.setattr(
        tasks,
        "build_extraction_service",
        lambda _session: OperationalFailureService(),
    )
    monkeypatch.setattr(process_document, "retry", request_retry)

    with pytest.raises(RetryRequested):
        process_document.run(str(job_id))

    with factory() as session:
        job = session.get(IngestionJob, job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.error_code is None
        assert job.error_message is None
