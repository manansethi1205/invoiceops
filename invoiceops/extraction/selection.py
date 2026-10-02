import uuid

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from invoiceops.extraction.supporting_hybrid import SUPPORTING_HYBRID_NAME
from invoiceops.extraction.version import CURRENT_EXTRACTION_STRATEGIES
from invoiceops.models import (
    ExtractionRun,
    ExtractionRunStatus,
    SupportingExtractionRun,
)
from invoiceops.schemas.cases import DocumentRole, SupportingExtractionStatus


def current_successful_extraction(session: Session, document_id: uuid.UUID) -> ExtractionRun | None:
    priorities = {
        f"{name}:{version}": index
        for index, (name, version) in enumerate(CURRENT_EXTRACTION_STRATEGIES)
    }
    strategy_key = ExtractionRun.extractor_name + ":" + ExtractionRun.extractor_version
    return session.scalar(
        select(ExtractionRun)
        .where(
            ExtractionRun.document_id == document_id,
            ExtractionRun.status == ExtractionRunStatus.SUCCEEDED,
            strategy_key.in_(priorities),
        )
        .order_by(case(priorities, value=strategy_key, else_=len(priorities)))
        .limit(1)
    )


def current_supporting_extraction(
    session: Session, document_id: uuid.UUID, role: DocumentRole
) -> SupportingExtractionRun | None:
    priority = case(
        (
            (SupportingExtractionRun.extractor_name == SUPPORTING_HYBRID_NAME)
            & (SupportingExtractionRun.status == SupportingExtractionStatus.SUCCEEDED),
            0,
        ),
        (SupportingExtractionRun.status == SupportingExtractionStatus.SUCCEEDED, 1),
        else_=2,
    )
    return session.scalar(
        select(SupportingExtractionRun)
        .where(
            SupportingExtractionRun.document_id == document_id,
            SupportingExtractionRun.role == role,
        )
        .order_by(
            priority, SupportingExtractionRun.created_at.desc(), SupportingExtractionRun.id.desc()
        )
        .limit(1)
    )
