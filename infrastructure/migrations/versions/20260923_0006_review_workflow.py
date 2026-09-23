"""Add evidence-linked review cases and tamper-evident events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0006"
down_revision: str | None = "20260921_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "review_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("OPEN", "CLAIMED", "RESOLVED", name="review_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("assigned_reviewer_id", sa.String(length=100), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution",
            sa.Enum(
                "ACCEPTED_EXCEPTION",
                "REJECTED_DOCUMENT",
                "CORRECTION_REQUESTED",
                name="review_resolution",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("version >= 1", name="ck_review_case_positive_version"),
        sa.CheckConstraint(
            "(status = 'OPEN' AND assigned_reviewer_id IS NULL AND claimed_at IS NULL "
            "AND resolved_at IS NULL AND resolution IS NULL AND resolution_reason IS NULL) OR "
            "(status = 'CLAIMED' AND assigned_reviewer_id IS NOT NULL "
            "AND claimed_at IS NOT NULL AND resolved_at IS NULL "
            "AND resolution IS NULL AND resolution_reason IS NULL) OR "
            "(status = 'RESOLVED' AND assigned_reviewer_id IS NOT NULL "
            "AND claimed_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND resolution IS NOT NULL AND length(trim(resolution_reason)) > 0)",
            name="ck_review_case_state_shape",
        ),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_run_id", name="uq_review_cases_match_run_id"),
    )
    op.create_index("ix_review_cases_match_run_id", "review_cases", ["match_run_id"])
    op.create_index("ix_review_cases_status", "review_cases", ["status"])

    op.create_table(
        "review_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_case_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "CASE_OPENED",
                "CASE_CLAIMED",
                "COMMENT_ADDED",
                "CASE_RELEASED",
                "CASE_RESOLVED",
                name="review_event_type",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_number >= 1", name="ck_review_event_positive_sequence"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_review_event_hash_length"),
        sa.CheckConstraint(
            "event_hash = lower(event_hash)", name="ck_review_event_hash_lowercase"
        ),
        sa.CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_review_event_previous_hash_length",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND previous_hash IS NULL) OR "
            "(sequence_number > 1 AND previous_hash IS NOT NULL)",
            name="ck_review_event_chain_shape",
        ),
        sa.CheckConstraint(
            "previous_hash IS NULL OR previous_hash = lower(previous_hash)",
            name="ck_review_event_previous_hash_lowercase",
        ),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_case_id", "sequence_number", name="uq_review_event_case_sequence"
        ),
    )
    op.create_index("ix_review_events_review_case_id", "review_events", ["review_case_id"])


def downgrade() -> None:
    op.drop_index("ix_review_events_review_case_id", table_name="review_events")
    op.drop_table("review_events")
    op.drop_index("ix_review_cases_status", table_name="review_cases")
    op.drop_index("ix_review_cases_match_run_id", table_name="review_cases")
    op.drop_table("review_cases")
