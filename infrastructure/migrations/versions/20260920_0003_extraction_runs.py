"""Add versioned extraction runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260920_0003"
down_revision: str | None = "20260916_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extractor_name", sa.String(length=100), nullable=False),
        sa.Column("extractor_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PROCESSING",
                "SUCCEEDED",
                "FAILED",
                name="extraction_run_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("used_ocr", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "extractor_name",
            "extractor_version",
            name="uq_extraction_run_document_extractor_version",
        ),
    )
    op.create_index("ix_extraction_runs_document_id", "extraction_runs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_extraction_runs_document_id", table_name="extraction_runs")
    op.drop_table("extraction_runs")
