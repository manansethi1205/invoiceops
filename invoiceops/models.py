import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from invoiceops.db import Base
from invoiceops.schemas.matching import MatchDecision
from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus


class JobStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExtractionRunStatus(StrEnum):
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelCallStatus(StrEnum):
    SKIPPED = "skipped"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    job: Mapped["IngestionJob"] = relationship(back_populates="document")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    match_runs: Mapped[list["MatchRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status", native_enum=False), default=JobStatus.QUEUED
    )
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    document: Mapped[Document] = relationship(back_populates="job")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "extractor_name",
            "extractor_version",
            name="uq_extraction_run_document_extractor_version",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    extractor_name: Mapped[str] = mapped_column(String(100))
    extractor_version: Mapped[str] = mapped_column(String(50))
    schema_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[ExtractionRunStatus] = mapped_column(
        Enum(ExtractionRunStatus, name="extraction_run_status", native_enum=False),
        default=ExtractionRunStatus.PROCESSING,
    )
    output_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    used_ocr: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document: Mapped[Document] = relationship(back_populates="extraction_runs")
    match_runs: Mapped[list["MatchRun"]] = relationship(back_populates="extraction_run")
    model_calls: Mapped[list["ModelCall"]] = relationship(
        back_populates="extraction_run", cascade="all, delete-orphan"
    )


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint(
            "extraction_run_id",
            "prompt_version",
            "request_fingerprint",
            name="uq_model_call_extraction_prompt_fingerprint",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50))
    requested_model: Mapped[str] = mapped_column(String(100))
    returned_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[ModelCallStatus] = mapped_column(
        Enum(ModelCallStatus, name="model_call_status", native_enum=False)
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    provider_response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    routing_json: Mapped[dict[str, object]] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    grounding_fusion_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="model_calls")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_po_number: Mapped[str] = mapped_column(String(100), index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_number",
    )
    match_runs: Mapped[list["MatchRun"]] = relationship(back_populates="purchase_order")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id", "line_number", name="uq_po_line_purchase_order_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    line_number: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(500))
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")


class MatchRun(Base):
    __tablename__ = "match_runs"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "purchase_order_id",
            "extraction_run_id",
            "policy_version",
            name="uq_match_run_idempotency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    policy_version: Mapped[str] = mapped_column(String(50))
    policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    decision: Mapped[MatchDecision] = mapped_column(
        Enum(MatchDecision, name="match_decision", native_enum=False)
    )
    result_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    document: Mapped[Document] = relationship(back_populates="match_runs")
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="match_runs")
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="match_runs")
    review_case: Mapped["ReviewCase | None"] = relationship(
        back_populates="match_run", cascade="all, delete-orphan", uselist=False
    )


class ReviewCase(Base):
    __tablename__ = "review_cases"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_review_case_positive_version"),
        CheckConstraint(
            "(status = 'OPEN' AND assigned_reviewer_id IS NULL AND claimed_at IS NULL "
            "AND resolved_at IS NULL AND resolution IS NULL AND resolution_reason IS NULL) OR "
            "(status = 'CLAIMED' AND assigned_reviewer_id IS NOT NULL "
            "AND claimed_at IS NOT NULL AND resolved_at IS NULL "
            "AND resolution IS NULL AND resolution_reason IS NULL) OR "
            "(status = 'RESOLVED' AND assigned_reviewer_id IS NOT NULL "
            "AND claimed_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND resolution IS NOT NULL AND length(trim(resolution_reason)) > 0)",
            name="ck_review_case_state_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", native_enum=False),
        default=ReviewStatus.OPEN,
    )
    assigned_reviewer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[ReviewResolution | None] = mapped_column(
        Enum(ReviewResolution, name="review_resolution", native_enum=False), nullable=True
    )
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_run: Mapped[MatchRun] = relationship(back_populates="review_case")
    events: Mapped[list["ReviewEvent"]] = relationship(
        back_populates="review_case",
        cascade="all, delete-orphan",
        order_by="ReviewEvent.sequence_number",
    )
    triggers: Mapped[list["ReviewCaseTrigger"]] = relationship(
        back_populates="review_case", cascade="all, delete-orphan"
    )


class ReviewEvent(Base):
    __tablename__ = "review_events"
    __table_args__ = (
        UniqueConstraint(
            "review_case_id", "sequence_number", name="uq_review_event_case_sequence"
        ),
        CheckConstraint("sequence_number >= 1", name="ck_review_event_positive_sequence"),
        CheckConstraint("length(event_hash) = 64", name="ck_review_event_hash_length"),
        CheckConstraint("event_hash = lower(event_hash)", name="ck_review_event_hash_lowercase"),
        CheckConstraint(
            "length(trim(hash_version)) > 0", name="ck_review_event_hash_version_nonblank"
        ),
        CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 64",
            name="ck_review_event_previous_hash_length",
        ),
        CheckConstraint(
            "(sequence_number = 1 AND previous_hash IS NULL) OR "
            "(sequence_number > 1 AND previous_hash IS NOT NULL)",
            name="ck_review_event_chain_shape",
        ),
        CheckConstraint(
            "previous_hash IS NULL OR previous_hash = lower(previous_hash)",
            name="ck_review_event_previous_hash_lowercase",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cases.id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[ReviewEventType] = mapped_column(
        Enum(ReviewEventType, name="review_event_type", native_enum=False)
    )
    actor_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    hash_version: Mapped[str] = mapped_column(String(50), default="review-audit-v2")
    previous_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_case: Mapped[ReviewCase] = relationship(back_populates="events")


class ReviewCaseTrigger(Base):
    __tablename__ = "review_case_triggers"
    __table_args__ = (
        CheckConstraint(
            "length(trim(trigger_type)) > 0", name="ck_review_case_trigger_type_nonblank"
        ),
        CheckConstraint(
            "length(trim(trigger_code)) > 0", name="ck_review_case_trigger_code_nonblank"
        ),
    )

    review_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cases.id", ondelete="CASCADE"), primary_key=True
    )
    trigger_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    trigger_code: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_case: Mapped[ReviewCase] = relationship(back_populates="triggers")
