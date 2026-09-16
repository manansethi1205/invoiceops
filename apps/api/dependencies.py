from functools import lru_cache

from invoiceops.config import get_settings
from invoiceops.ingestion.dispatch import CeleryJobDispatcher, JobDispatcher
from invoiceops.ingestion.storage import ObjectStore, S3ObjectStore


@lru_cache
def get_object_store() -> ObjectStore:
    return S3ObjectStore(get_settings())


@lru_cache
def get_dispatcher() -> JobDispatcher:
    return CeleryJobDispatcher()

