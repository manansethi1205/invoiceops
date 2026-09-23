"""Add versioned duplicate risk and surrogate review-trigger identifiers."""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0008"
down_revision: str | None = "20260924_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_assessments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "disposition",
            sa.Enum(
                "CLEAR",
                "NEEDS_REVIEW",
                "NOT_ASSESSABLE",
                name="risk_disposition",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("feature_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(policy_version)) > 0", name="ck_risk_assessment_policy_nonblank"
        ),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_run_id", "policy_version", name="uq_risk_assessment_match_policy"
        ),
    )
    op.create_index(
        "ix_risk_assessments_match_run_id", "risk_assessments", ["match_run_id"]
    )
    op.create_table(
        "risk_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_assessment_id", sa.Uuid(), nullable=False),
        sa.Column(
            "code",
            sa.Enum(
                "EXACT_BUSINESS_KEY_DUPLICATE",
                "REUSED_VENDOR_INVOICE_NUMBER",
                "SAME_PO_INVOICE_REPLAY",
                "NEAR_DUPLICATE",
                "DUPLICATE_CHECK_INCOMPLETE",
                name="risk_signal_code",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("INFO", "WARNING", "CRITICAL", name="risk_severity", native_enum=False),
            nullable=False,
        ),
        sa.Column("comparison_match_run_id", sa.Uuid(), nullable=True),
        sa.Column("observed", sa.JSON(), nullable=False),
        sa.Column("reference", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(explanation)) > 0", name="ck_risk_signal_explanation_nonblank"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_match_run_id"], ["match_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["risk_assessment_id"], ["risk_assessments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "risk_assessment_id",
            "code",
            "comparison_match_run_id",
            name="uq_risk_signal_logical",
        ),
    )
    op.create_index(
        "ix_risk_signals_risk_assessment_id", "risk_signals", ["risk_assessment_id"]
    )
    _replace_review_triggers_with_surrogate_key()


def downgrade() -> None:
    _restore_review_trigger_composite_key()
    op.drop_index("ix_risk_signals_risk_assessment_id", table_name="risk_signals")
    op.drop_table("risk_signals")
    op.drop_index("ix_risk_assessments_match_run_id", table_name="risk_assessments")
    op.drop_table("risk_assessments")


def _replace_review_triggers_with_surrogate_key() -> None:
    op.create_table(
        "review_case_triggers_v2",
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "review_case_id",
            "trigger_type",
            "trigger_code",
            "source_id",
            name="uq_review_case_trigger_logical",
        ),
    )
    connection = op.get_bind()
    old = sa.table(
        "review_case_triggers",
        sa.column("review_case_id", sa.Uuid()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_code", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    new = sa.table(
        "review_case_triggers_v2",
        sa.column("id", sa.Uuid()),
        sa.column("review_case_id", sa.Uuid()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_code", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = connection.execute(sa.select(old)).mappings()
    values = [
        {
            "id": uuid.uuid5(
                uuid.NAMESPACE_URL,
                "invoiceops:review-trigger:"
                f"{row['review_case_id']}:{row['trigger_type']}:"
                f"{row['trigger_code']}:{row['source_id']}",
            ),
            **dict(row),
        }
        for row in rows
    ]
    if values:
        connection.execute(new.insert(), values)
    op.drop_index("ix_review_case_triggers_lookup", table_name="review_case_triggers")
    op.drop_table("review_case_triggers")
    op.rename_table("review_case_triggers_v2", "review_case_triggers")
    op.create_index(
        "ix_review_case_triggers_lookup",
        "review_case_triggers",
        ["trigger_type", "trigger_code", "review_case_id"],
    )


def _restore_review_trigger_composite_key() -> None:
    op.create_table(
        "review_case_triggers_v1",
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
    connection = op.get_bind()
    current = sa.table(
        "review_case_triggers",
        sa.column("review_case_id", sa.Uuid()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_code", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    restored = sa.table(
        "review_case_triggers_v1",
        sa.column("review_case_id", sa.Uuid()),
        sa.column("trigger_type", sa.String()),
        sa.column("trigger_code", sa.String()),
        sa.column("source_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    connection.execute(restored.insert().from_select(
        ["review_case_id", "trigger_type", "trigger_code", "source_id", "created_at"],
        sa.select(
            current.c.review_case_id,
            current.c.trigger_type,
            current.c.trigger_code,
            current.c.source_id,
            current.c.created_at,
        ),
    ))
    op.drop_index("ix_review_case_triggers_lookup", table_name="review_case_triggers")
    op.drop_table("review_case_triggers")
    op.rename_table("review_case_triggers_v1", "review_case_triggers")
    op.create_index(
        "ix_review_case_triggers_lookup",
        "review_case_triggers",
        ["trigger_type", "trigger_code", "review_case_id"],
    )
