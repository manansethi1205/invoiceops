"""Add evidence-backed payable cases and supporting-document confirmation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_0013"
down_revision: str | None = "20260926_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payable_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.String(40), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version >= 1", name="ck_payable_case_positive_version"),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0", name="ck_payable_case_idempotency_nonblank"
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_payable_case_fingerprint_length"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_number"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_payable_cases_case_number", "payable_cases", ["case_number"], unique=True)

    op.create_table(
        "case_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("attachment_order", sa.Integer(), nullable=False),
        sa.Column("active_slot", sa.String(50), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("attachment_order >= 1", name="ck_case_document_positive_order"),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_case_document_fingerprint_length"
        ),
        sa.ForeignKeyConstraint(["case_id"], ["payable_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["case_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "active_slot", name="uq_case_document_active_slot"),
        sa.UniqueConstraint("case_id", "attachment_order", name="uq_case_document_order"),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_case_document_idempotency"),
        sa.UniqueConstraint(
            "case_id", "role", "document_id", name="uq_case_document_role_document"
        ),
        sa.UniqueConstraint("supersedes_id", name="uq_case_document_supersedes"),
    )
    op.create_index("ix_case_documents_case_id", "case_documents", ["case_id"])
    op.create_index("ix_case_documents_document_id", "case_documents", ["document_id"])

    op.create_table(
        "supporting_extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("extractor_name", sa.String(100), nullable=False),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("used_ocr", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.String(255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "role",
            "extractor_name",
            "extractor_version",
            name="uq_support_extraction_document_role_version",
        ),
    )
    op.create_index(
        "ix_supporting_extraction_runs_document_id", "supporting_extraction_runs", ["document_id"]
    )

    op.create_table(
        "case_confirmations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("case_document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("extractor_version", sa.String(50), nullable=False),
        sa.Column("canonical_record_type", sa.String(50), nullable=False),
        sa.Column("canonical_record_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_json", sa.JSON(), nullable=False),
        sa.Column("corrected_fields", sa.JSON(), nullable=False),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_case_confirmation_fingerprint_length"
        ),
        sa.ForeignKeyConstraint(["case_id"], ["payable_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_document_id"], ["case_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["supporting_extraction_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_document_id", name="uq_case_confirmation_attachment"),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_case_confirmation_idempotency"),
    )
    op.create_index("ix_case_confirmations_case_id", "case_confirmations", ["case_id"])
    op.create_index(
        "ix_case_confirmations_case_document_id", "case_confirmations", ["case_document_id"]
    )
    op.create_index(
        "ix_case_confirmations_extraction_run_id", "case_confirmations", ["extraction_run_id"]
    )

    op.create_table(
        "case_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_key", sa.String(150), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("stage", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("message", sa.String(255), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("document_role", sa.String(30), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence_number >= 1", name="ck_case_event_positive_sequence"),
        sa.ForeignKeyConstraint(["case_id"], ["payable_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "event_key", name="uq_case_event_case_key"),
        sa.UniqueConstraint("case_id", "sequence_number", name="uq_case_event_case_sequence"),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])

    op.create_table(
        "case_match_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["case_id"], ["payable_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_case_match_context_idempotency"),
        sa.UniqueConstraint("case_id", "request_fingerprint", name="uq_case_match_context_request"),
    )
    op.create_index("ix_case_match_contexts_case_id", "case_match_contexts", ["case_id"])
    op.create_index("ix_case_match_contexts_match_run_id", "case_match_contexts", ["match_run_id"])


def downgrade() -> None:
    op.drop_index("ix_case_match_contexts_match_run_id", table_name="case_match_contexts")
    op.drop_index("ix_case_match_contexts_case_id", table_name="case_match_contexts")
    op.drop_table("case_match_contexts")
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
    op.drop_index("ix_case_confirmations_extraction_run_id", table_name="case_confirmations")
    op.drop_index("ix_case_confirmations_case_document_id", table_name="case_confirmations")
    op.drop_index("ix_case_confirmations_case_id", table_name="case_confirmations")
    op.drop_table("case_confirmations")
    op.drop_index(
        "ix_supporting_extraction_runs_document_id", table_name="supporting_extraction_runs"
    )
    op.drop_table("supporting_extraction_runs")
    op.drop_index("ix_case_documents_document_id", table_name="case_documents")
    op.drop_index("ix_case_documents_case_id", table_name="case_documents")
    op.drop_table("case_documents")
    op.drop_index("ix_payable_cases_case_number", table_name="payable_cases")
    op.drop_table("payable_cases")
