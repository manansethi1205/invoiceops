"""Make three-way allocations idempotent per uploaded invoice document."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260924_0010"
down_revision: str | None = "20260924_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.add_column(sa.Column("document_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE three_way_allocations "
            "SET document_id = ("
            "SELECT match_runs.document_id FROM match_runs "
            "WHERE match_runs.id = three_way_allocations.match_run_id"
            ")"
        )
    )
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.alter_column("document_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_three_way_allocations_document_id_documents",
            "documents",
            ["document_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_three_way_allocation_document_invoice_line",
            ["document_id", "invoice_line_index"],
        )
        batch_op.create_index("ix_three_way_allocations_document_id", ["document_id"])


def downgrade() -> None:
    with op.batch_alter_table("three_way_allocations") as batch_op:
        batch_op.drop_index("ix_three_way_allocations_document_id")
        batch_op.drop_constraint(
            "uq_three_way_allocation_document_invoice_line", type_="unique"
        )
        batch_op.drop_constraint(
            "fk_three_way_allocations_document_id_documents", type_="foreignkey"
        )
        batch_op.drop_column("document_id")
