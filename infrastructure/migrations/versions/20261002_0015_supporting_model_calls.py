"""Record routed supporting-model invocations without invoice-only foreign keys."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_0015"
down_revision: str | None = "20261001_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supporting_model_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("supporting_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "PURCHASE_ORDER",
                "GOODS_RECEIPT",
                "DELIVERY_NOTE",
                name="support_model_role",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("requested_model", sa.String(100), nullable=False),
        sa.Column("returned_model", sa.String(100)),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "SKIPPED",
                "PROCESSING",
                "SUCCEEDED",
                "FAILED",
                name="support_model_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("input_document_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("routing_json", sa.JSON(), nullable=False),
        sa.Column("candidate_json", sa.JSON()),
        sa.Column("grounding_json", sa.JSON()),
        sa.Column("provider_response_id", sa.String(255)),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("error_code", sa.String(100)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["supporting_run_id"], ["supporting_extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "supporting_run_id",
            "prompt_version",
            "request_fingerprint",
            name="uq_support_model_run_prompt_fingerprint",
        ),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="ck_support_model_fingerprint"),
        sa.CheckConstraint(
            "length(input_document_hash) = 64", name="ck_support_model_document_hash"
        ),
        sa.CheckConstraint(
            "role IN ('PURCHASE_ORDER', 'GOODS_RECEIPT', 'DELIVERY_NOTE')",
            name="ck_support_model_role",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_support_model_latency"
        ),
    )
    op.create_index(
        "ix_supporting_model_calls_supporting_run_id",
        "supporting_model_calls",
        ["supporting_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_supporting_model_calls_supporting_run_id", "supporting_model_calls")
    op.drop_table("supporting_model_calls")
