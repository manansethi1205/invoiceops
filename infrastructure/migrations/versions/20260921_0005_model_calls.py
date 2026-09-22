"""Add idempotent VLM model-call lineage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0005"
down_revision: str | None = "20260921_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("requested_model", sa.String(length=100), nullable=False),
        sa.Column("returned_model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SKIPPED", "PROCESSING", "SUCCEEDED", "FAILED",
                name="model_call_status", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("routing_json", sa.JSON(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("candidate_json", sa.JSON(), nullable=True),
        sa.Column("grounding_fusion_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["extraction_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "extraction_run_id", "prompt_version", "request_fingerprint",
            name="uq_model_call_extraction_prompt_fingerprint",
        ),
    )
    op.create_index("ix_model_calls_extraction_run_id", "model_calls", ["extraction_run_id"])


def downgrade() -> None:
    op.drop_index("ix_model_calls_extraction_run_id", table_name="model_calls")
    op.drop_table("model_calls")
