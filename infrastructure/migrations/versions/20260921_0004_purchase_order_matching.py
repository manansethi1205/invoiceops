"""Add purchase orders and deterministic match runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260921_0004"
down_revision: str | None = "20260920_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_po_number", sa.String(length=100), nullable=False),
        sa.Column("vendor_name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_purchase_orders_external_po_number",
        "purchase_orders",
        ["external_po_number"],
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_order_id", "line_number", name="uq_po_line_purchase_order_number"
        ),
    )
    op.create_index(
        "ix_purchase_order_lines_purchase_order_id",
        "purchase_order_lines",
        ["purchase_order_id"],
    )
    op.create_table(
        "match_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=50), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum("MATCHED", "NEEDS_REVIEW", name="match_decision", native_enum=False),
            nullable=False,
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "purchase_order_id",
            "extraction_run_id",
            "policy_version",
            name="uq_match_run_idempotency",
        ),
    )
    op.create_index("ix_match_runs_document_id", "match_runs", ["document_id"])
    op.create_index("ix_match_runs_purchase_order_id", "match_runs", ["purchase_order_id"])
    op.create_index("ix_match_runs_extraction_run_id", "match_runs", ["extraction_run_id"])


def downgrade() -> None:
    op.drop_index("ix_match_runs_extraction_run_id", table_name="match_runs")
    op.drop_index("ix_match_runs_purchase_order_id", table_name="match_runs")
    op.drop_index("ix_match_runs_document_id", table_name="match_runs")
    op.drop_table("match_runs")
    op.drop_index(
        "ix_purchase_order_lines_purchase_order_id", table_name="purchase_order_lines"
    )
    op.drop_table("purchase_order_lines")
    op.drop_index("ix_purchase_orders_external_po_number", table_name="purchase_orders")
    op.drop_table("purchase_orders")
