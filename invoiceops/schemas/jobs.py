import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from invoiceops.models import JobStatus


class UploadAccepted(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    status_url: str
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


class ErrorBody(BaseModel):
    detail: str
