import pytest

from tests.conftest import MemoryObjectStore


def test_memory_object_store_round_trip() -> None:
    store = MemoryObjectStore()
    store.put("invoices/example.pdf", b"pdf bytes", "application/pdf")

    assert store.get("invoices/example.pdf") == b"pdf bytes"


def test_memory_object_store_missing_key_is_explicit() -> None:
    store = MemoryObjectStore()

    with pytest.raises(KeyError):
        store.get("missing")
