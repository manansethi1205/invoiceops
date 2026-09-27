"""Add durable resumable job events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_0012"
down_revision: str | None = "20260924_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence_number >= 1", name="ck_job_event_positive_sequence"),
        sa.CheckConstraint("length(trim(event_type)) > 0", name="ck_job_event_type_nonblank"),
        sa.CheckConstraint("length(trim(event_key)) > 0", name="ck_job_event_key_nonblank"),
        sa.CheckConstraint("length(trim(stage)) > 0", name="ck_job_event_stage_nonblank"),
        sa.CheckConstraint("length(trim(status)) > 0", name="ck_job_event_status_nonblank"),
        sa.CheckConstraint("length(trim(message)) > 0", name="ck_job_event_message_nonblank"),
        sa.CheckConstraint(
            "trace_id IS NULL OR length(trace_id) = 32",
            name="ck_job_event_trace_id_length",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["ingestion_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "event_key", name="uq_job_event_job_key"),
        sa.UniqueConstraint("job_id", "sequence_number", name="uq_job_event_job_sequence"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
