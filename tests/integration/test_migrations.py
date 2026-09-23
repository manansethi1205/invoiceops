from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from invoiceops.config import get_settings


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
    }.issubset(inspect(engine).get_table_names())

    # Simulate an existing repository at the pre-review schema, then apply only this slice.
    command.downgrade(config, "20260921_0005")
    assert "model_calls" in inspect(engine).get_table_names()
    assert "review_cases" not in inspect(engine).get_table_names()
    assert "review_events" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "review_cases" in inspect(engine).get_table_names()
    assert "review_events" in inspect(engine).get_table_names()

    command.downgrade(config, "20260920_0003")
    assert "match_runs" not in inspect(engine).get_table_names()
    assert "model_calls" not in inspect(engine).get_table_names()
    assert "review_cases" not in inspect(engine).get_table_names()
    assert "review_events" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "match_runs" in inspect(engine).get_table_names()
    assert "model_calls" in inspect(engine).get_table_names()
    assert "review_cases" in inspect(engine).get_table_names()
    assert "review_events" in inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()
