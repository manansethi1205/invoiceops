import hashlib
import uuid
from datetime import date, datetime
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
from invoiceops.schemas.matching import MatchDecision, MatchingMode
from invoiceops.schemas.review import ReviewEventType, ReviewResolution, ReviewStatus
from invoiceops.schemas.risk import RiskDisposition, RiskSeverity, RiskSignalCode

TWO_WAY_CONTEXT_FINGERPRINT = hashlib.sha256(b"invoiceops:two-way-context:v1").hexdigest()


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    job: Mapped["IngestionJob"] = relationship(back_populates="document")
    extraction_runs: Mapped[list["ExtractionRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    match_runs: Mapped[list["MatchRun"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    three_way_allocations: Mapped[list["ThreeWayAllocation"]] = relationship(
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="model_calls")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    external_po_number: Mapped[str] = mapped_column(String(100), index=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLine.line_number",
    )
    match_runs: Mapped[list["MatchRun"]] = relationship(back_populates="purchase_order")
    goods_receipts: Mapped[list["GoodsReceipt"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


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
    receipt_lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="purchase_order_line"
    )
    three_way_allocations: Mapped[list["ThreeWayAllocation"]] = relationship(
        back_populates="purchase_order_line"
    )


class GoodsReceipt(Base):
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint(
            "purchase_order_id",
            "external_receipt_number",
            name="uq_goods_receipt_po_external_number",
        ),
        CheckConstraint(
            "length(trim(external_receipt_number)) > 0",
            name="ck_goods_receipt_number_nonblank",
        ),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="ck_goods_receipt_fingerprint_length",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    external_receipt_number: Mapped[str] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="goods_receipts")
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        order_by="GoodsReceiptLine.purchase_order_line_id",
    )
    reversal: Mapped["GoodsReceiptReversal | None"] = relationship(
        back_populates="goods_receipt", cascade="all, delete-orphan", uselist=False
    )


class GoodsReceiptLine(Base):
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (
        UniqueConstraint(
            "goods_receipt_id",
            "purchase_order_line_id",
            name="uq_goods_receipt_line_receipt_po_line",
        ),
        CheckConstraint("accepted_quantity > 0", name="ck_goods_receipt_line_positive_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"), index=True
    )
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    goods_receipt: Mapped[GoodsReceipt] = relationship(back_populates="lines")
    purchase_order_line: Mapped[PurchaseOrderLine] = relationship(back_populates="receipt_lines")


class GoodsReceiptReversal(Base):
    __tablename__ = "goods_receipt_reversals"
    __table_args__ = (
        CheckConstraint("length(trim(actor_id)) > 0", name="ck_receipt_reversal_actor_nonblank"),
        CheckConstraint("length(trim(reason)) > 0", name="ck_receipt_reversal_reason_nonblank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    goods_receipt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"), unique=True, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    reversed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    goods_receipt: Mapped[GoodsReceipt] = relationship(back_populates="reversal")


class MatchRun(Base):
    __tablename__ = "match_runs"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "purchase_order_id",
            "extraction_run_id",
            "policy_version",
            "matching_mode",
            "matching_context_fingerprint",
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
    matching_mode: Mapped[MatchingMode] = mapped_column(
        Enum(MatchingMode, name="matching_mode", native_enum=False),
        default=MatchingMode.TWO_WAY,
    )
    matching_context_fingerprint: Mapped[str] = mapped_column(
        String(64), default=TWO_WAY_CONTEXT_FINGERPRINT
    )
    risk_policy_version: Mapped[str] = mapped_column(String(50), default="duplicate-risk-v1")
    decision: Mapped[MatchDecision] = mapped_column(
        Enum(MatchDecision, name="match_decision", native_enum=False)
    )
    result_json: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    document: Mapped[Document] = relationship(back_populates="match_runs")
    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="match_runs")
    extraction_run: Mapped[ExtractionRun] = relationship(back_populates="match_runs")
    review_case: Mapped["ReviewCase | None"] = relationship(
        back_populates="match_run", cascade="all, delete-orphan", uselist=False
    )
    risk_assessments: Mapped[list["RiskAssessment"]] = relationship(
        back_populates="match_run", cascade="all, delete-orphan"
    )
    risk_feature_record: Mapped["RiskFeatureRecord | None"] = relationship(
        back_populates="match_run", cascade="all, delete-orphan", uselist=False
    )
    three_way_context: Mapped["ThreeWayContext | None"] = relationship(
        back_populates="match_run", cascade="all, delete-orphan", uselist=False
    )
    three_way_allocations: Mapped[list["ThreeWayAllocation"]] = relationship(
        back_populates="match_run", cascade="all, delete-orphan"
    )


class RiskFeatureRecord(Base):
    __tablename__ = "risk_feature_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    normalized_vendor: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    normalized_invoice_number: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    invoice_date: Mapped[date | None] = mapped_column(nullable=True, index=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, index=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True, index=True)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    missing_fields: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    match_run: Mapped[MatchRun] = relationship(back_populates="risk_feature_record")


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        UniqueConstraint("match_run_id", "policy_version", name="uq_risk_assessment_match_policy"),
        CheckConstraint(
            "length(trim(policy_version)) > 0", name="ck_risk_assessment_policy_nonblank"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), index=True
    )
    policy_version: Mapped[str] = mapped_column(String(50))
    policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    disposition: Mapped[RiskDisposition] = mapped_column(
        Enum(RiskDisposition, name="risk_disposition", native_enum=False)
    )
    feature_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    candidate_metrics: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    match_run: Mapped[MatchRun] = relationship(back_populates="risk_assessments")
    signals: Mapped[list["RiskSignal"]] = relationship(
        back_populates="risk_assessment",
        cascade="all, delete-orphan",
        order_by="RiskSignal.code, RiskSignal.comparison_match_run_id, RiskSignal.id",
    )


class RiskSignal(Base):
    __tablename__ = "risk_signals"
    __table_args__ = (
        UniqueConstraint(
            "risk_assessment_id",
            "code",
            "comparison_match_run_id",
            name="uq_risk_signal_logical",
        ),
        CheckConstraint(
            "length(trim(explanation)) > 0", name="ck_risk_signal_explanation_nonblank"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    risk_assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("risk_assessments.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[RiskSignalCode] = mapped_column(
        Enum(RiskSignalCode, name="risk_signal_code", native_enum=False)
    )
    severity: Mapped[RiskSeverity] = mapped_column(
        Enum(RiskSeverity, name="risk_severity", native_enum=False)
    )
    comparison_match_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("match_runs.id", ondelete="RESTRICT"), nullable=True
    )
    observed: Mapped[dict[str, object]] = mapped_column(JSON)
    reference: Mapped[dict[str, object]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    risk_assessment: Mapped[RiskAssessment] = relationship(back_populates="signals")


class ThreeWayContext(Base):
    __tablename__ = "three_way_contexts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), unique=True, index=True
    )
    context_fingerprint: Mapped[str] = mapped_column(String(64))
    replay_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    match_run: Mapped[MatchRun] = relationship(back_populates="three_way_context")


class ThreeWayAllocation(Base):
    __tablename__ = "three_way_allocations"
    __table_args__ = (
        UniqueConstraint(
            "match_run_id",
            "purchase_order_line_id",
            "invoice_line_index",
            name="uq_three_way_allocation_logical",
        ),
        UniqueConstraint(
            "document_id",
            "purchase_order_id",
            "invoice_line_index",
            name="uq_three_way_allocation_document_po_invoice_line",
        ),
        CheckConstraint("allocated_quantity > 0", name="ck_three_way_allocation_positive_quantity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    match_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match_runs.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    extraction_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="RESTRICT"), index=True
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"), index=True
    )
    invoice_line_index: Mapped[int] = mapped_column(Integer)
    allocated_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    match_run: Mapped[MatchRun] = relationship(back_populates="three_way_allocations")
    document: Mapped[Document] = relationship(back_populates="three_way_allocations")
    purchase_order_line: Mapped[PurchaseOrderLine] = relationship(
        back_populates="three_way_allocations"
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
        UniqueConstraint("review_case_id", "sequence_number", name="uq_review_event_case_sequence"),
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
        UniqueConstraint(
            "review_case_id",
            "trigger_type",
            "trigger_code",
            "source_id",
            name="uq_review_case_trigger_logical",
        ),
        CheckConstraint(
            "length(trim(trigger_type)) > 0", name="ck_review_case_trigger_type_nonblank"
        ),
        CheckConstraint(
            "length(trim(trigger_code)) > 0", name="ck_review_case_trigger_code_nonblank"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    review_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("review_cases.id", ondelete="CASCADE")
    )
    trigger_type: Mapped[str] = mapped_column(String(50))
    trigger_code: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[uuid.UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_case: Mapped[ReviewCase] = relationship(back_populates="triggers")
