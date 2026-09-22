from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from invoiceops.config import get_settings


def test_matching_migration_upgrades_clean_and_existing_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    engine = create_engine(database_url)
    assert {"purchase_orders", "purchase_order_lines", "match_runs", "model_calls"}.issubset(
        inspect(engine).get_table_names()
    )

    command.downgrade(config, "20260920_0003")
    assert "match_runs" not in inspect(engine).get_table_names()
    assert "model_calls" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "match_runs" in inspect(engine).get_table_names()
    assert "model_calls" in inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()
