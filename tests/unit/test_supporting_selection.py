import uuid

from sqlalchemy.orm import Session, sessionmaker

from invoiceops.extraction.selection import current_supporting_extraction
from invoiceops.extraction.supporting import (
    SUPPORTING_EXTRACTOR_NAME,
    SUPPORTING_EXTRACTOR_VERSION,
)
from invoiceops.extraction.supporting_hybrid import (
    SUPPORTING_HYBRID_NAME,
    SUPPORTING_HYBRID_VERSION,
)
from invoiceops.models import Document, SupportingExtractionRun
from invoiceops.schemas.cases import DocumentRole, SupportingExtractionStatus


def test_current_version_baseline_beats_old_hybrid_and_current_hybrid_wins(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as session:
        document = Document(
            original_filename="synthetic.pdf",
            content_type="application/pdf",
            byte_size=1,
            sha256=uuid.uuid4().hex * 2,
            object_key=uuid.uuid4().hex,
        )
        session.add(document)
        session.flush()

        def add_run(name: str, version: str) -> SupportingExtractionRun:
            run = SupportingExtractionRun(
                document_id=document.id,
                role=DocumentRole.PURCHASE_ORDER,
                extractor_name=name,
                extractor_version=version,
                schema_version="1.0",
                status=SupportingExtractionStatus.SUCCEEDED,
                output_json={},
            )
            session.add(run)
            session.flush()
            return run

        old_baseline = add_run(SUPPORTING_EXTRACTOR_NAME, "0.2.0")
        assert current_supporting_extraction(
            session, document.id, DocumentRole.PURCHASE_ORDER
        ) == old_baseline
        old_hybrid = add_run(SUPPORTING_HYBRID_NAME, "0.3.0")
        assert old_hybrid.id != old_baseline.id
        current_baseline = add_run(SUPPORTING_EXTRACTOR_NAME, SUPPORTING_EXTRACTOR_VERSION)
        assert (
            current_supporting_extraction(session, document.id, DocumentRole.PURCHASE_ORDER)
            == current_baseline
        )
        current_hybrid = add_run(SUPPORTING_HYBRID_NAME, SUPPORTING_HYBRID_VERSION)
        assert (
            current_supporting_extraction(session, document.id, DocumentRole.PURCHASE_ORDER)
            == current_hybrid
        )
