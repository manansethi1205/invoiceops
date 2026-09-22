import uuid

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from invoiceops.extraction.version import CURRENT_EXTRACTION_STRATEGIES
from invoiceops.models import ExtractionRun, ExtractionRunStatus


def current_successful_extraction(
    session: Session, document_id: uuid.UUID
) -> ExtractionRun | None:
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
