"""Decouple risk history and add immutable three-way matching context."""

import hashlib
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0009"
down_revision: str | None = "20260924_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TWO_WAY_CONTEXT_FINGERPRINT = hashlib.sha256(b"invoiceops:two-way-context:v1").hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("match_runs") as batch_op:
        batch_op.drop_constraint("uq_match_run_idempotency", type_="unique")
        batch_op.add_column(
            sa.Column(
                "matching_mode",
                sa.Enum("TWO_WAY", "THREE_WAY", name="matching_mode", native_enum=False),
                nullable=False,
                server_default="TWO_WAY",
            )
        )
        batch_op.add_column(
            sa.Column(
                "matching_context_fingerprint",
                sa.String(length=64),
                nullable=False,
                server_default=TWO_WAY_CONTEXT_FINGERPRINT,
            )
        )
        batch_op.add_column(
            sa.Column(
                "risk_policy_version",
                sa.String(length=50),
                nullable=False,
                server_default="duplicate-risk-v1",
            )
        )
        batch_op.create_unique_constraint(
            "uq_match_run_idempotency",
            [
                "document_id",
                "purchase_order_id",
                "extraction_run_id",
                "policy_version",
                "matching_mode",
                "matching_context_fingerprint",
            ],
        )

    with op.batch_alter_table("risk_assessments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "candidate_metrics",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )

    op.create_table(
        "risk_feature_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_vendor", sa.String(length=255), nullable=True),
        sa.Column("normalized_invoice_number", sa.String(length=255), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("total", sa.Numeric(24, 8), nullable=True),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("extraction_run_id", sa.Uuid(), nullable=False),
        sa.Column("missing_fields", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["extraction_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_run_id", name="uq_risk_feature_record_match_run"),
    )
    for column in (
        "match_run_id",
        "normalized_vendor",
        "normalized_invoice_number",
        "invoice_date",
        "currency",
        "total",
        "purchase_order_id",
        "document_id",
        "extraction_run_id",
    ):
        op.create_index(f"ix_risk_feature_records_{column}", "risk_feature_records", [column])
    op.create_index(
        "ix_risk_feature_vendor_invoice",
        "risk_feature_records",
        ["normalized_vendor", "normalized_invoice_number"],
    )
    op.create_index(
        "ix_risk_feature_vendor_currency_date",
        "risk_feature_records",
        ["normalized_vendor", "currency", "invoice_date"],
    )
    _backfill_risk_features()

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("external_receipt_number", sa.String(length=100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(external_receipt_number)) > 0",
            name="ck_goods_receipt_number_nonblank",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64", name="ck_goods_receipt_fingerprint_length"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_order_id",
            "external_receipt_number",
            name="uq_goods_receipt_po_external_number",
        ),
    )
    op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_quantity", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint(
            "accepted_quantity > 0", name="ck_goods_receipt_line_positive_quantity"
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id"], ["purchase_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "goods_receipt_id",
            "purchase_order_line_id",
            name="uq_goods_receipt_line_receipt_po_line",
        ),
    )
    op.create_index(
        "ix_goods_receipt_lines_goods_receipt_id",
        "goods_receipt_lines",
        ["goods_receipt_id"],
    )
    op.create_index(
        "ix_goods_receipt_lines_purchase_order_line_id",
        "goods_receipt_lines",
        ["purchase_order_line_id"],
    )
    op.create_table(
        "goods_receipt_reversals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(actor_id)) > 0", name="ck_receipt_reversal_actor_nonblank"
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0", name="ck_receipt_reversal_reason_nonblank"
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goods_receipt_id", name="uq_goods_receipt_reversal_receipt"),
    )
    op.create_index(
        "ix_goods_receipt_reversals_goods_receipt_id",
        "goods_receipt_reversals",
        ["goods_receipt_id"],
        unique=True,
    )
    op.create_table(
        "three_way_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("context_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_run_id", name="uq_three_way_context_match_run"),
    )
    op.create_index("ix_three_way_contexts_match_run_id", "three_way_contexts", ["match_run_id"])
    op.create_table(
        "three_way_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_run_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_line_index", sa.Integer(), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "allocated_quantity > 0", name="ck_three_way_allocation_positive_quantity"
        ),
        sa.ForeignKeyConstraint(["match_run_id"], ["match_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["purchase_order_line_id"], ["purchase_order_lines.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_run_id",
            "purchase_order_line_id",
            "invoice_line_index",
            name="uq_three_way_allocation_logical",
        ),
    )
    op.create_index(
        "ix_three_way_allocations_match_run_id",
        "three_way_allocations",
        ["match_run_id"],
    )
    op.create_index(
        "ix_three_way_allocations_purchase_order_line_id",
        "three_way_allocations",
        ["purchase_order_line_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_three_way_allocations_purchase_order_line_id",
        table_name="three_way_allocations",
    )
    op.drop_index("ix_three_way_allocations_match_run_id", table_name="three_way_allocations")
    op.drop_table("three_way_allocations")
    op.drop_index("ix_three_way_contexts_match_run_id", table_name="three_way_contexts")
    op.drop_table("three_way_contexts")
    op.drop_index(
        "ix_goods_receipt_reversals_goods_receipt_id",
        table_name="goods_receipt_reversals",
    )
    op.drop_table("goods_receipt_reversals")
    op.drop_index(
        "ix_goods_receipt_lines_purchase_order_line_id", table_name="goods_receipt_lines"
    )
    op.drop_index(
        "ix_goods_receipt_lines_goods_receipt_id", table_name="goods_receipt_lines"
    )
    op.drop_table("goods_receipt_lines")
    op.drop_index("ix_goods_receipts_purchase_order_id", table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_index("ix_risk_feature_vendor_currency_date", table_name="risk_feature_records")
    op.drop_index("ix_risk_feature_vendor_invoice", table_name="risk_feature_records")
    for column in reversed(
        (
            "match_run_id",
            "normalized_vendor",
            "normalized_invoice_number",
            "invoice_date",
            "currency",
            "total",
            "purchase_order_id",
            "document_id",
            "extraction_run_id",
        )
    ):
        op.drop_index(f"ix_risk_feature_records_{column}", table_name="risk_feature_records")
    op.drop_table("risk_feature_records")
    with op.batch_alter_table("risk_assessments") as batch_op:
        batch_op.drop_column("candidate_metrics")
    with op.batch_alter_table("match_runs") as batch_op:
        batch_op.drop_constraint("uq_match_run_idempotency", type_="unique")
        batch_op.create_unique_constraint(
            "uq_match_run_idempotency",
            ["document_id", "purchase_order_id", "extraction_run_id", "policy_version"],
        )
        batch_op.drop_column("risk_policy_version")
        batch_op.drop_column("matching_context_fingerprint")
        batch_op.drop_column("matching_mode")


def _backfill_risk_features() -> None:
    connection = op.get_bind()
    assessments = sa.table(
        "risk_assessments",
        sa.column("id", sa.Uuid()),
        sa.column("match_run_id", sa.Uuid()),
        sa.column("feature_snapshot", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    records = sa.table(
        "risk_feature_records",
        sa.column("id", sa.Uuid()),
        sa.column("match_run_id", sa.Uuid()),
        sa.column("normalized_vendor", sa.String()),
        sa.column("normalized_invoice_number", sa.String()),
        sa.column("invoice_date", sa.Date()),
        sa.column("currency", sa.String()),
        sa.column("total", sa.Numeric()),
        sa.column("purchase_order_id", sa.Uuid()),
        sa.column("document_id", sa.Uuid()),
        sa.column("extraction_run_id", sa.Uuid()),
        sa.column("missing_fields", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = connection.execute(
        sa.select(assessments).order_by(assessments.c.created_at, assessments.c.id)
    ).mappings()
    seen: set[object] = set()
    values: list[dict[str, object]] = []
    for row in rows:
        if row["match_run_id"] in seen:
            continue
        snapshot = row["feature_snapshot"]
        if not isinstance(snapshot, dict):
            continue
        seen.add(row["match_run_id"])
        total = snapshot.get("total")
        values.append(
            {
                "id": uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"invoiceops:risk-feature:{row['match_run_id']}",
                ),
                "match_run_id": row["match_run_id"],
                "normalized_vendor": snapshot.get("normalized_vendor"),
                "normalized_invoice_number": snapshot.get("normalized_invoice_number"),
                "invoice_date": (
                    date.fromisoformat(str(snapshot["invoice_date"]))
                    if snapshot.get("invoice_date") is not None
                    else None
                ),
                "currency": snapshot.get("currency"),
                "total": Decimal(str(total)) if total is not None else None,
                "purchase_order_id": uuid.UUID(str(snapshot["purchase_order_id"])),
                "document_id": uuid.UUID(str(snapshot["document_id"])),
                "extraction_run_id": uuid.UUID(str(snapshot["extraction_run_id"])),
                "missing_fields": snapshot.get("missing_fields", []),
                "created_at": row["created_at"],
            }
        )
    if values:
        connection.execute(records.insert(), values)
