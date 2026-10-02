"""Persist optional confirmed purchase-order line totals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261001_0014"
down_revision: str | None = "20260930_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_order_lines",
        sa.Column("line_total", sa.Numeric(precision=24, scale=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("purchase_order_lines", "line_total")
