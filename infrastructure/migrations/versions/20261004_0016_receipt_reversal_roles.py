"""Retain verified role context on receipt reversal audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261004_0016"
down_revision: str | None = "20261002_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Legacy reversals keep NULL; their historical roles cannot be inferred.
    op.add_column("goods_receipt_reversals", sa.Column("actor_roles", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("goods_receipt_reversals", "actor_roles")
