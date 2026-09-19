import uuid
from datetime import datetime

from pydantic import BaseModel

from invoiceops.models import ExtractionRunStatus
from invoiceops.schemas.extraction import Invoice


class ExtractorMetadata(BaseModel):
    name: str
    version: str
    schema_version: str


class ExtractionPendingRead(BaseModel):
    document_id: uuid.UUID
    status: ExtractionRunStatus


class ExtractionResultRead(BaseModel):
    document_id: uuid.UUID
    status: ExtractionRunStatus
    extractor: ExtractorMetadata
    used_ocr: bool | None
    latency_ms: float | None
    invoice: Invoice | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None
