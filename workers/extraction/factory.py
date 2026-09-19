from sqlalchemy.orm import Session

from invoiceops.config import get_settings
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.service import ExtractionService
from invoiceops.ingestion.storage import S3ObjectStore


def build_extraction_service(session: Session) -> ExtractionService:
    return ExtractionService(
        session=session,
        object_store=S3ObjectStore(get_settings()),
        text_extractor=DocumentTextExtractor(),
        invoice_extractor=DeterministicInvoiceExtractor(),
    )
