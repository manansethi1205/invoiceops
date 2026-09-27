import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from invoiceops.models import JobStatus


class UploadAccepted(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID
    status: JobStatus
    status_url: str
    events_url: str
    extraction_url: str
    deduplicated: bool


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    status: JobStatus
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class JobEventType(StrEnum):
    UPLOAD_ACCEPTED = "upload.accepted"
    DOCUMENT_VALIDATED = "document.validated"
    EXTRACTION_STARTED = "extraction.started"
    EXTRACTION_COMPLETED = "extraction.completed"
    PROCESSING_COMPLETED = "processing.completed"
    PROCESSING_FAILED = "processing.failed"
    HEARTBEAT = "heartbeat"


class JobEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    sequence: int
    event_type: JobEventType
    stage: str
    status: str
    message: str
    occurred_at: datetime
    trace_id: str | None
    payload: dict[str, object]


class ErrorBody(BaseModel):
    detail: str
