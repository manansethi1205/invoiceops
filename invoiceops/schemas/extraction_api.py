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
    hybrid: "HybridMetadata | None" = None


class HybridMetadata(BaseModel):
    strategy: str
    routing_reasons: list[str]
    provider_invoked: bool
    provider: str | None
    model: str | None
    prompt_version: str | None
    grounding_summary: dict[str, object] | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    provider_latency_ms: float | None
    provider_failure_code: str | None
