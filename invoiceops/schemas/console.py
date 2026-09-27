import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from invoiceops.models import JobStatus
from invoiceops.schemas.matching import MatchDecision
from invoiceops.schemas.review import ReviewStatus


class InvoiceSummary(BaseModel):
    document_id: uuid.UUID
    filename: str
    content_type: str
    byte_size: int
    created_at: datetime
    job_id: uuid.UUID
    job_status: JobStatus
    invoice_number: str | None
    currency: str | None
    total: Decimal | None
    latest_match_run_id: uuid.UUID | None
    match_decision: MatchDecision | None
    review_case_id: uuid.UUID | None
    review_status: ReviewStatus | None


class InvoiceSummaryPage(BaseModel):
    items: list[InvoiceSummary]
    next_cursor: uuid.UUID | None


class DashboardSummary(BaseModel):
    documents_total: int
    jobs_processing: int
    jobs_failed: int
    reviews_waiting: int
    oldest_waiting_review_opened_at: datetime | None

