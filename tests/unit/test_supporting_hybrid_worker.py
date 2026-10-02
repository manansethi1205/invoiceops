from sqlalchemy.orm import Session, sessionmaker

from invoiceops.config import Settings
from invoiceops.extraction.supporting_service import SupportingExtractionService
from invoiceops.models import CaseDocument
from tests.conftest import MemoryObjectStore
from tests.integration.test_supporting_hybrid_service import attachment
from workers.extraction import factory, tasks


def test_worker_dispatches_supporting_attachment_through_configured_service(
    db_session_factory: sessionmaker[Session], object_store: MemoryObjectStore,
    monkeypatch,
) -> None:
    with db_session_factory() as session:
        item = attachment(session, object_store)
        item_id = item.id
    seen: list[str] = []

    class RecordingService:
        def process(self, value: CaseDocument) -> None:
            seen.append(str(value.id))

    monkeypatch.setattr(tasks, "SessionLocal", db_session_factory)
    monkeypatch.setattr(
        tasks, "build_supporting_extraction_service", lambda _session: RecordingService()
    )
    tasks.process_supporting_document.run(str(item_id))
    assert seen == [str(item_id)]


def test_supporting_provider_is_disabled_by_default(
    db_session_factory: sessionmaker[Session], monkeypatch,
) -> None:
    settings = Settings(_env_file=None, supporting_vlm_enabled=False)
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    with db_session_factory() as session:
        service = factory.build_supporting_extraction_service(session)
    assert isinstance(service, SupportingExtractionService)
