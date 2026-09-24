import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, create_engine, inspect, select

from invoiceops.config import get_settings
from invoiceops.review.audit import AUDIT_HASH_V1, event_hash
from invoiceops.schemas.review import ReviewEventType


def test_workflow_migrations_upgrade_clean_and_existing_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert {
        "purchase_orders",
        "purchase_order_lines",
        "match_runs",
        "model_calls",
        "review_cases",
        "review_events",
        "review_case_triggers",
        "risk_assessments",
        "risk_signals",
        "risk_feature_records",
        "goods_receipts",
        "goods_receipt_lines",
        "goods_receipt_reversals",
        "three_way_contexts",
        "three_way_allocations",
    }.issubset(inspect(engine).get_table_names())

    # Simulate an existing repository at the pre-review schema, then apply only this slice.
    command.downgrade(config, "20260921_0005")
    assert "model_calls" in inspect(engine).get_table_names()
    assert "review_cases" not in inspect(engine).get_table_names()
    assert "review_events" not in inspect(engine).get_table_names()
    assert "review_case_triggers" not in inspect(engine).get_table_names()
    assert "risk_assessments" not in inspect(engine).get_table_names()
    assert "risk_signals" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "review_cases" in inspect(engine).get_table_names()
    assert "review_events" in inspect(engine).get_table_names()
    assert "review_case_triggers" in inspect(engine).get_table_names()
    assert "risk_assessments" in inspect(engine).get_table_names()
    assert "risk_signals" in inspect(engine).get_table_names()

    command.downgrade(config, "20260920_0003")
    assert "match_runs" not in inspect(engine).get_table_names()
    assert "model_calls" not in inspect(engine).get_table_names()
    assert "review_cases" not in inspect(engine).get_table_names()
    assert "review_events" not in inspect(engine).get_table_names()
    assert "review_case_triggers" not in inspect(engine).get_table_names()
    assert "risk_assessments" not in inspect(engine).get_table_names()
    assert "risk_signals" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "match_runs" in inspect(engine).get_table_names()
    assert "model_calls" in inspect(engine).get_table_names()
    assert "review_cases" in inspect(engine).get_table_names()
    assert "review_events" in inspect(engine).get_table_names()
    assert "review_case_triggers" in inspect(engine).get_table_names()
    assert "risk_assessments" in inspect(engine).get_table_names()
    assert "risk_signals" in inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()


def test_audit_v2_migration_preserves_v1_events_and_backfills_triggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "audit-migration-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "20260923_0006")
    engine = create_engine(database_url)
    metadata = MetaData()
    metadata.reflect(engine)
    document_id = uuid.uuid4()
    extraction_id = uuid.uuid4()
    purchase_order_id = uuid.uuid4()
    match_run_id = uuid.uuid4()
    case_id = uuid.uuid4()
    event_id = uuid.uuid4()
    occurred_at = datetime(2026, 9, 24, 8, 0, tzinfo=UTC)
    payload: dict[str, object] = {
        "match_run_id": str(match_run_id),
        "reason_codes": ["CURRENCY_MISMATCH"],
    }
    digest = event_hash(
        case_id=case_id,
        sequence_number=1,
        event_type=ReviewEventType.CASE_OPENED,
        actor_id="system:matching",
        occurred_at=occurred_at,
        payload=payload,
        previous_hash=None,
        hash_version=AUDIT_HASH_V1,
    )
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["documents"].insert(),
            {
                "id": document_id.hex,
                "original_filename": "synthetic.pdf",
                "content_type": "application/pdf",
                "byte_size": 1,
                "sha256": "a" * 64,
                "object_key": "synthetic/a.pdf",
                "created_at": occurred_at,
            },
        )
        connection.execute(
            metadata.tables["extraction_runs"].insert(),
            {
                "id": extraction_id.hex,
                "document_id": document_id.hex,
                "extractor_name": "deterministic-baseline",
                "extractor_version": "0.2.0",
                "schema_version": "invoice-v1",
                "status": "SUCCEEDED",
                "created_at": occurred_at,
            },
        )
        connection.execute(
            metadata.tables["purchase_orders"].insert(),
            {
                "id": purchase_order_id.hex,
                "external_po_number": "PO-MIGRATION",
                "currency": "USD",
                "created_at": occurred_at,
            },
        )
        connection.execute(
            metadata.tables["match_runs"].insert(),
            {
                "id": match_run_id.hex,
                "document_id": document_id.hex,
                "purchase_order_id": purchase_order_id.hex,
                "extraction_run_id": extraction_id.hex,
                "policy_version": "matching-v1",
                "policy_snapshot": {},
                "decision": "NEEDS_REVIEW",
                "result_json": {"reason_codes": ["CURRENCY_MISMATCH"]},
                "created_at": occurred_at,
            },
        )
        connection.execute(
            metadata.tables["review_cases"].insert(),
            {
                "id": case_id.hex,
                "match_run_id": match_run_id.hex,
                "status": "OPEN",
                "version": 1,
                "opened_at": occurred_at,
            },
        )
        connection.execute(
            metadata.tables["review_events"].insert(),
            {
                "id": event_id.hex,
                "review_case_id": case_id.hex,
                "sequence_number": 1,
                "event_type": "CASE_OPENED",
                "actor_id": "system:matching",
                "payload": payload,
                "previous_hash": None,
                "event_hash": digest,
                "occurred_at": occurred_at,
            },
        )

    command.upgrade(config, "head")
    migrated = MetaData()
    migrated.reflect(engine)
    with engine.connect() as connection:
        version = connection.scalar(
            select(migrated.tables["review_events"].c.hash_version).where(
                migrated.tables["review_events"].c.id == event_id.hex
            )
        )
        trigger = (
            connection.execute(
                select(migrated.tables["review_case_triggers"]).where(
                    migrated.tables["review_case_triggers"].c.review_case_id == case_id.hex
                )
            )
            .mappings()
            .one()
        )
    assert version == AUDIT_HASH_V1
    assert trigger["id"] is not None
    assert trigger["trigger_type"] == "MATCH_REASON"
    assert trigger["trigger_code"] == "CURRENCY_MISMATCH"
    assert str(trigger["source_id"]).replace("-", "") == match_run_id.hex
    engine.dispose()
    get_settings.cache_clear()
