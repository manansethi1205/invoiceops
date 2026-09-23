"""Version review hashes and normalize review-case triggers."""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0007"
down_revision: str | None = "20260923_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("review_events") as batch_op:
        batch_op.add_column(
            sa.Column(
                "hash_version",
                sa.String(length=50),
                nullable=False,
                server_default="review-audit-v1",
            )
        )
        batch_op.create_check_constraint(
            "ck_review_event_hash_version_nonblank", "length(trim(hash_version)) > 0"
        )

    op.create_table(
        "review_case_triggers",
        sa.Column("review_case_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_code", sa.String(length=100), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(trigger_type)) > 0", name="ck_review_case_trigger_type_nonblank"
        ),
        sa.CheckConstraint(
            "length(trim(trigger_code)) > 0", name="ck_review_case_trigger_code_nonblank"
        ),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint(
            "review_case_id", "trigger_type", "trigger_code", "source_id"
        ),
    )
    op.create_index(
        "ix_review_case_triggers_lookup",
        "review_case_triggers",
        ["trigger_type", "trigger_code", "review_case_id"],
    )
    _backfill_match_reason_triggers()
    with op.batch_alter_table("review_events") as batch_op:
        batch_op.alter_column(
            "hash_version",
            existing_type=sa.String(length=50),
            existing_nullable=False,
            server_default="review-audit-v2",
        )


def downgrade() -> None:
    op.drop_index("ix_review_case_triggers_lookup", table_name="review_case_triggers")
    op.drop_table("review_case_triggers")
    with op.batch_alter_table("review_events") as batch_op:
        batch_op.drop_constraint("ck_review_event_hash_version_nonblank", type_="check")
        batch_op.drop_column("hash_version")


def _backfill_match_reason_triggers() -> None:
    review_cases = sa.table(
        "review_cases",
        sa.column("id", sa.Uuid()),
        sa.column("match_run_id", sa.Uuid()),
        sa.column("opened_at", sa.DateTime(timezone=True)),
    )
    match_runs = sa.table(
        "match_runs",
        sa.column("id", sa.Uuid()),
        sa.column("result_json", sa.JSON()),
    )
    triggers = sa.table(
        "review_case_triggers",
        sa.column("review_case_id", sa.Uuid()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_code", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            review_cases.c.id.label("case_id"),
            review_cases.c.match_run_id,
            review_cases.c.opened_at,
            match_runs.c.result_json,
        ).join(match_runs, match_runs.c.id == review_cases.c.match_run_id)
    ).mappings()
    values: list[dict[str, object]] = []
    for row in rows:
        result = row["result_json"]
        if isinstance(result, str):
            result = json.loads(result)
        if not isinstance(result, dict):
            continue
        reason_codes = result.get("reason_codes", [])
        if not isinstance(reason_codes, list):
            continue
        for reason_code in dict.fromkeys(str(code) for code in reason_codes):
            values.append(
                {
                    "review_case_id": row["case_id"],
                    "trigger_type": "MATCH_REASON",
                    "trigger_code": reason_code,
                    "source_id": row["match_run_id"],
                    "created_at": row["opened_at"],
                }
            )
    if values:
        connection.execute(triggers.insert(), values)
