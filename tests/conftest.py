from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.dependencies import get_dispatcher, get_object_store
from apps.api.main import app
from invoiceops.config import Settings, get_settings
from invoiceops.db import Base, get_db


class MemoryObjectStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, body: bytes, content_type: str) -> None:
        self.objects[key] = (body, content_type)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class RecordingDispatcher:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    def enqueue(self, job_id: str) -> None:
        self.job_ids.append(job_id)


@pytest.fixture
def object_store() -> MemoryObjectStore:
    return MemoryObjectStore()


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def db_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(
    object_store: MemoryObjectStore,
    dispatcher: RecordingDispatcher,
    db_session_factory: sessionmaker[Session],
) -> Generator[TestClient, None, None]:
    def override_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_object_store] = lambda: object_store
    app.dependency_overrides[get_dispatcher] = lambda: dispatcher
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite+pysqlite://", max_upload_bytes=1024
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
