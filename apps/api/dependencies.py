from functools import lru_cache

from sqlalchemy.orm import Session, sessionmaker

from invoiceops.config import get_settings
from invoiceops.db import SessionLocal
from invoiceops.ingestion.dispatch import CeleryJobDispatcher, JobDispatcher
from invoiceops.ingestion.storage import ObjectStore, S3ObjectStore


@lru_cache
def get_object_store() -> ObjectStore:
    return S3ObjectStore(get_settings())


@lru_cache
def get_dispatcher() -> JobDispatcher:
    return CeleryJobDispatcher()


def get_session_factory() -> sessionmaker[Session]:
    return SessionLocal

