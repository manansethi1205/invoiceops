"""Make document checksums unique for ingestion idempotency."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260916_0002"
down_revision: str | None = "20260915_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # This project has only synthetic development data. Preserve the oldest row per checksum.
    op.execute(
        """
        DELETE FROM documents
        WHERE id IN (
            SELECT id
            FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY sha256 ORDER BY created_at, id
                ) AS duplicate_number
                FROM documents
            ) ranked
            WHERE duplicate_number > 1
        )
        """
    )
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)
