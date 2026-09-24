"""Add reconciliation identity and provenance to three-way allocations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0011"
down_revision: str | None = "20260924_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("three_way_contexts") as batch_op:
        batch_op.add_column(sa.Column("replay_fingerprint", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE three_way_contexts SET replay_fingerprint = context_fingerprint"
        )
    )
    with op.batch_alter_table("three_way_contexts") as batch_op:
        batch_op.alter_column("replay_fingerprint", nullable=False)
        batch_op.create_index("ix_three_way_contexts_replay_fingerprint", ["replay_fingerprint"])
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.add_column(sa.Column("purchase_order_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("extraction_run_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE three_way_allocations SET "
            "purchase_order_id = (SELECT purchase_order_id FROM match_runs "
            "WHERE match_runs.id = three_way_allocations.match_run_id), "
            "extraction_run_id = (SELECT extraction_run_id FROM match_runs "
            "WHERE match_runs.id = three_way_allocations.match_run_id)"
        )
    )
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.alter_column("purchase_order_id", nullable=False)
        batch_op.alter_column("extraction_run_id", nullable=False)
        batch_op.drop_constraint(
            "uq_three_way_allocation_document_invoice_line", type_="unique"
        )
        batch_op.create_foreign_key(
            "fk_three_way_allocations_purchase_order_id_purchase_orders",
            "purchase_orders",
            ["purchase_order_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_three_way_allocations_extraction_run_id_extraction_runs",
            "extraction_runs",
            ["extraction_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint(
            "uq_three_way_allocation_document_po_invoice_line",
            ["document_id", "purchase_order_id", "invoice_line_index"],
        )
        batch_op.create_index("ix_three_way_allocations_purchase_order_id", ["purchase_order_id"])
        batch_op.create_index("ix_three_way_allocations_extraction_run_id", ["extraction_run_id"])


def downgrade() -> None:
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.drop_index("ix_three_way_allocations_extraction_run_id")
        batch_op.drop_index("ix_three_way_allocations_purchase_order_id")
        batch_op.drop_constraint(
            "uq_three_way_allocation_document_po_invoice_line", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_three_way_allocations_extraction_run_id_extraction_runs", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_three_way_allocations_purchase_order_id_purchase_orders", type_="foreignkey"
        )
        batch_op.create_unique_constraint(
            "uq_three_way_allocation_document_invoice_line",
            ["document_id", "invoice_line_index"],
        )
        batch_op.drop_column("extraction_run_id")
        batch_op.drop_column("purchase_order_id")
    with op.batch_alter_table("three_way_contexts") as batch_op:
        batch_op.drop_index("ix_three_way_contexts_replay_fingerprint")
        batch_op.drop_column("replay_fingerprint")
