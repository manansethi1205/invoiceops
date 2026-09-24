import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from apps.api.dependencies import get_dispatcher, get_object_store
from invoiceops.config import Settings, get_settings
from invoiceops.db import get_db
from invoiceops.extraction.selection import current_successful_extraction
from invoiceops.ingestion.dispatch import JobDispatcher
from invoiceops.ingestion.service import (
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionService,
    UnsupportedDocumentError,
    UploadCommand,
)
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.logging import configure_logging
from invoiceops.matching.service import (
    DocumentNotFoundError,
    ExtractionNotReadyError,
    MatchingService,
    MatchRunNotFoundError,
    PurchaseOrderNotFoundError,
    PurchaseOrderService,
    match_run_to_read,
    purchase_order_to_read,
)
from invoiceops.models import (
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    IngestionJob,
    ModelCall,
    ModelCallStatus,
    ThreeWayContext,
)
from invoiceops.receipts.service import (
    ConflictingReceiptReplayError,
    GoodsReceiptAlreadyReversedError,
    GoodsReceiptNotFoundError,
    GoodsReceiptService,
    ReceiptLineNotFoundError,
    ReceiptPurchaseOrderNotFoundError,
    goods_receipt_to_read,
)
from invoiceops.review.service import (
    InvalidReviewCursorError,
    ReviewCaseNotFoundError,
    ReviewService,
    review_case_to_read,
)
from invoiceops.review.state import ReviewTransitionError
from invoiceops.risk.service import DuplicateRiskService, RiskAssessmentNotFoundError
from invoiceops.schemas.extraction import Invoice
from invoiceops.schemas.extraction_api import (
    ExtractionPendingRead,
    ExtractionResultRead,
    ExtractorMetadata,
    HybridMetadata,
)
from invoiceops.schemas.jobs import ErrorBody, JobRead, UploadAccepted
from invoiceops.schemas.matching import (
    MatchCreate,
    MatchRunRead,
    PurchaseOrderCreate,
    PurchaseOrderRead,
    ReasonCode,
)
from invoiceops.schemas.receipts import (
    GoodsReceiptCreate,
    GoodsReceiptRead,
    ReverseGoodsReceiptCommand,
)
from invoiceops.schemas.review import (
    AuditVerificationRead,
    CommentCommand,
    ReleaseCommand,
    ResolveCommand,
    ReviewCaseDetail,
    ReviewCasePage,
    ReviewCaseRead,
    ReviewEventRead,
    ReviewStatus,
    ReviewTriggerType,
    VersionedCommand,
)
from invoiceops.schemas.risk import RiskAssessmentRead
from invoiceops.schemas.three_way import ThreeWayContextRead, ThreeWayContextSnapshot

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)
app = FastAPI(title="InvoiceOps API", version="0.1.0")


def get_reviewer_id(
    value: Annotated[str | None, Header(alias="X-Reviewer-ID")] = None,
) -> str:
    reviewer_id = value.strip() if value is not None else ""
    if not reviewer_id or len(reviewer_id) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_REVIEWER_ID",
                "message": "X-Reviewer-ID must contain 1 to 100 nonblank characters",
            },
        )
    return reviewer_id


def get_actor_id(
    value: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
) -> str:
    actor_id = value.strip() if value is not None else ""
    if not actor_id or len(actor_id) > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_ACTOR_ID",
                "message": "X-Actor-ID must contain 1 to 100 nonblank characters",
            },
        )
    return actor_id


def review_conflict(exc: ReviewTransitionError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})


def review_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "REVIEW_CASE_NOT_FOUND", "message": "Review case not found"},
    )


@app.middleware("http")
async def structured_request_log(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "HTTP request failed",
            extra={
                "event": "http.request_failed",
                "request_method": request.method,
                "request_path": request.url.path,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        raise
    if request.url.path != "/healthz":
        logger.info(
            "HTTP request completed",
            extra={
                "event": "http.request_completed",
                "request_method": request.method,
                "request_path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
    return response


@app.get("/healthz", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/v1/invoices",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={400: {"model": ErrorBody}, 413: {"model": ErrorBody}, 415: {"model": ErrorBody}},
    tags=["invoices"],
)
def upload_invoice(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF, JPEG, or PNG invoice")],
    session: Annotated[Session, Depends(get_db)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    dispatcher: Annotated[JobDispatcher, Depends(get_dispatcher)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UploadAccepted:
    # A bounded read prevents an arbitrarily large request from being retained in memory.
    body = file.file.read(settings.max_upload_bytes + 1)
    service = IngestionService(session, object_store, dispatcher, settings.max_upload_bytes)
    try:
        result = service.ingest(
            UploadCommand(
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                body=body,
            )
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(status_code=415, detail=f"Unsupported content type: {exc}") from exc
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail="The uploaded file is empty") from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=f"The uploaded file exceeds {settings.max_upload_bytes} bytes",
        ) from exc

    return UploadAccepted(
        job_id=result.job.id,
        document_id=result.job.document_id,
        status=result.job.status,
        status_url=str(request.url_for("get_job", job_id=str(result.job.id))),
        extraction_url=str(
            request.url_for("get_extraction", document_id=str(result.job.document_id))
        ),
        deduplicated=not result.created,
    )


@app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get(
    "/v1/invoices/{document_id}/extraction",
    response_model=ExtractionPendingRead | ExtractionResultRead,
    tags=["invoices"],
)
def get_extraction(
    document_id: uuid.UUID,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> ExtractionPendingRead | ExtractionResultRead:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    run = current_successful_extraction(session, document_id)
    if run is None:
        terminal = session.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.document_id == document_id)
            .order_by(ExtractionRun.created_at.desc())
        )
        if terminal is not None and terminal.status == ExtractionRunStatus.FAILED:
            run = terminal
        else:
            response.status_code = status.HTTP_202_ACCEPTED
            return ExtractionPendingRead(
                document_id=document_id,
                status=ExtractionRunStatus.PROCESSING,
            )

    model_call = session.scalar(
        select(ModelCall)
        .where(ModelCall.extraction_run_id == run.id)
        .order_by(ModelCall.created_at.desc())
    )
    hybrid = None
    if model_call is not None:
        raw_reasons = model_call.routing_json.get("reasons", [])
        routing_reasons = raw_reasons if isinstance(raw_reasons, list) else []
        hybrid = HybridMetadata(
            strategy=f"{run.extractor_name}@{run.extractor_version}",
            routing_reasons=[str(reason) for reason in routing_reasons],
            provider_invoked=model_call.status != ModelCallStatus.SKIPPED,
            provider=model_call.provider,
            model=model_call.returned_model or model_call.requested_model,
            prompt_version=model_call.prompt_version,
            grounding_summary=model_call.grounding_fusion_json,
            input_tokens=model_call.input_tokens,
            output_tokens=model_call.output_tokens,
            total_tokens=model_call.total_tokens,
            provider_latency_ms=model_call.latency_ms,
            provider_failure_code=model_call.error_code,
        )

    invoice = Invoice.model_validate(run.output_json) if run.output_json is not None else None
    return ExtractionResultRead(
        document_id=document_id,
        status=run.status,
        extractor=ExtractorMetadata(
            name=run.extractor_name,
            version=run.extractor_version,
            schema_version=run.schema_version,
        ),
        used_ocr=run.used_ocr,
        latency_ms=run.latency_ms,
        invoice=invoice,
        error_code=run.error_code,
        created_at=run.created_at,
        completed_at=run.completed_at,
        hybrid=hybrid,
    )


@app.post(
    "/v1/purchase-orders",
    response_model=PurchaseOrderRead,
    status_code=status.HTTP_201_CREATED,
    tags=["purchase-orders"],
)
def create_purchase_order(
    command: PurchaseOrderCreate,
    session: Annotated[Session, Depends(get_db)],
) -> PurchaseOrderRead:
    purchase_order = PurchaseOrderService(session).create(command)
    return purchase_order_to_read(purchase_order)


@app.get(
    "/v1/purchase-orders/{purchase_order_id}",
    response_model=PurchaseOrderRead,
    tags=["purchase-orders"],
)
def get_purchase_order(
    purchase_order_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> PurchaseOrderRead:
    try:
        purchase_order = PurchaseOrderService(session).get(purchase_order_id)
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found") from exc
    return purchase_order_to_read(purchase_order)


@app.post(
    "/v1/goods-receipts",
    response_model=GoodsReceiptRead,
    status_code=status.HTTP_201_CREATED,
    tags=["goods-receipts"],
)
def create_goods_receipt(
    command: GoodsReceiptCreate,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> GoodsReceiptRead:
    try:
        result = GoodsReceiptService(session).create(command)
    except ReceiptPurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found") from exc
    except ReceiptLineNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase order line not found") from exc
    except ConflictingReceiptReplayError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONFLICTING_RECEIPT_REPLAY",
                "message": "The receipt number already exists with a different payload",
            },
        ) from exc
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return goods_receipt_to_read(result.receipt)


@app.get("/v1/goods-receipts", response_model=list[GoodsReceiptRead], tags=["goods-receipts"])
def list_goods_receipts(
    session: Annotated[Session, Depends(get_db)],
    purchase_order_id: uuid.UUID | None = None,
) -> list[GoodsReceiptRead]:
    return [
        goods_receipt_to_read(item) for item in GoodsReceiptService(session).list(purchase_order_id)
    ]


@app.get(
    "/v1/purchase-orders/{purchase_order_id}/goods-receipts",
    response_model=list[GoodsReceiptRead],
    tags=["goods-receipts"],
)
def list_purchase_order_goods_receipts(
    purchase_order_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> list[GoodsReceiptRead]:
    try:
        PurchaseOrderService(session).get(purchase_order_id)
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found") from exc
    return [
        goods_receipt_to_read(item) for item in GoodsReceiptService(session).list(purchase_order_id)
    ]


@app.get(
    "/v1/goods-receipts/{receipt_id}",
    response_model=GoodsReceiptRead,
    tags=["goods-receipts"],
)
def get_goods_receipt(
    receipt_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]
) -> GoodsReceiptRead:
    try:
        return goods_receipt_to_read(GoodsReceiptService(session).get(receipt_id))
    except GoodsReceiptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Goods receipt not found") from exc


@app.post(
    "/v1/goods-receipts/{receipt_id}/reverse",
    response_model=GoodsReceiptRead,
    tags=["goods-receipts"],
)
def reverse_goods_receipt(
    receipt_id: uuid.UUID,
    command: ReverseGoodsReceiptCommand,
    actor_id: Annotated[str, Depends(get_actor_id)],
    session: Annotated[Session, Depends(get_db)],
) -> GoodsReceiptRead:
    try:
        receipt = GoodsReceiptService(session).reverse(receipt_id, actor_id, command.reason)
    except GoodsReceiptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Goods receipt not found") from exc
    except GoodsReceiptAlreadyReversedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "RECEIPT_ALREADY_REVERSED", "message": "Receipt already reversed"},
        ) from exc
    return goods_receipt_to_read(receipt)


@app.post(
    "/v1/documents/{document_id}/matches",
    response_model=MatchRunRead,
    status_code=status.HTTP_201_CREATED,
    tags=["matching"],
)
def create_match(
    document_id: uuid.UUID,
    command: MatchCreate,
    response: Response,
    session: Annotated[Session, Depends(get_db)],
) -> MatchRunRead:
    try:
        result = MatchingService(session).match(
            document_id, command.purchase_order_id, command.mode
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Document not found") from exc
    except PurchaseOrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Purchase order not found") from exc
    except ExtractionNotReadyError as exc:
        raise HTTPException(
            status_code=409,
            detail="A successful current extraction is required before matching",
        ) from exc
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return match_run_to_read(result.run)


@app.get(
    "/v1/matches/{match_run_id}",
    response_model=MatchRunRead,
    tags=["matching"],
)
def get_match(
    match_run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> MatchRunRead:
    try:
        run = MatchingService(session).get(match_run_id)
    except MatchRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Match run not found") from exc
    return match_run_to_read(run)


@app.get(
    "/v1/matches/{match_run_id}/three-way-context",
    response_model=ThreeWayContextRead,
    tags=["matching"],
)
def get_three_way_context(
    match_run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> ThreeWayContextRead:
    context = session.scalar(
        select(ThreeWayContext).where(ThreeWayContext.match_run_id == match_run_id)
    )
    if context is None:
        raise HTTPException(status_code=404, detail="Three-way context not found")
    return ThreeWayContextRead(
        match_run_id=context.match_run_id,
        context_fingerprint=context.context_fingerprint,
        snapshot=ThreeWayContextSnapshot.model_validate(context.snapshot),
        created_at=context.created_at,
    )


def risk_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "RISK_ASSESSMENT_NOT_FOUND", "message": "Risk assessment not found"},
    )


@app.get(
    "/v1/matches/{match_run_id}/risk",
    response_model=RiskAssessmentRead,
    tags=["risk"],
)
def get_match_risk(
    match_run_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> RiskAssessmentRead:
    service = DuplicateRiskService(session)
    try:
        return service.read(service.get_for_match(match_run_id))
    except RiskAssessmentNotFoundError as exc:
        raise risk_not_found() from exc


@app.get(
    "/v1/risk-assessments/{risk_assessment_id}",
    response_model=RiskAssessmentRead,
    tags=["risk"],
)
def get_risk_assessment(
    risk_assessment_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> RiskAssessmentRead:
    service = DuplicateRiskService(session)
    try:
        return service.read(service.get(risk_assessment_id))
    except RiskAssessmentNotFoundError as exc:
        raise risk_not_found() from exc


@app.get("/v1/review-cases", response_model=ReviewCasePage, tags=["review"])
def list_review_cases(
    session: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[ReviewStatus | None, Query(alias="status")] = None,
    assignee: str | None = None,
    reason_code: ReasonCode | None = None,
    trigger_type: ReviewTriggerType | None = None,
    trigger_code: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    created_before: datetime | None = None,
    created_after: datetime | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ReviewCasePage:
    try:
        return ReviewService(session).list_cases(
            status=status_filter,
            assignee=assignee,
            reason_code=reason_code,
            trigger_type=trigger_type,
            trigger_code=trigger_code,
            created_before=created_before,
            created_after=created_after,
            cursor=cursor,
            limit=limit,
        )
    except InvalidReviewCursorError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_CURSOR", "message": str(exc)},
        ) from exc


@app.get("/v1/review-cases/{case_id}", response_model=ReviewCaseDetail, tags=["review"])
def get_review_case(
    case_id: uuid.UUID,
    request: Request,
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseDetail:
    try:
        return ReviewService(session).detail(
            case_id,
            events_url=str(request.url_for("get_review_events", case_id=str(case_id))),
            audit_verification_url=str(
                request.url_for("verify_review_audit", case_id=str(case_id))
            ),
        )
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc


@app.post("/v1/review-cases/{case_id}/claim", response_model=ReviewCaseRead, tags=["review"])
def claim_review_case(
    case_id: uuid.UUID,
    command: VersionedCommand,
    reviewer_id: Annotated[str, Depends(get_reviewer_id)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).claim(case_id, reviewer_id, command.expected_version)
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
    except ReviewTransitionError as exc:
        raise review_conflict(exc) from exc
    return review_case_to_read(case)


@app.post("/v1/review-cases/{case_id}/release", response_model=ReviewCaseRead, tags=["review"])
def release_review_case(
    case_id: uuid.UUID,
    command: ReleaseCommand,
    reviewer_id: Annotated[str, Depends(get_reviewer_id)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).release(
            case_id, reviewer_id, command.expected_version, command.reason
        )
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
    except ReviewTransitionError as exc:
        raise review_conflict(exc) from exc
    return review_case_to_read(case)


@app.post("/v1/review-cases/{case_id}/comments", response_model=ReviewCaseRead, tags=["review"])
def add_review_comment(
    case_id: uuid.UUID,
    command: CommentCommand,
    reviewer_id: Annotated[str, Depends(get_reviewer_id)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).comment(
            case_id, reviewer_id, command.expected_version, command.comment
        )
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
    except ReviewTransitionError as exc:
        raise review_conflict(exc) from exc
    return review_case_to_read(case)


@app.post("/v1/review-cases/{case_id}/resolve", response_model=ReviewCaseRead, tags=["review"])
def resolve_review_case(
    case_id: uuid.UUID,
    command: ResolveCommand,
    reviewer_id: Annotated[str, Depends(get_reviewer_id)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).resolve(
            case_id,
            reviewer_id,
            command.expected_version,
            command.resolution,
            command.reason,
        )
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
    except ReviewTransitionError as exc:
        raise review_conflict(exc) from exc
    return review_case_to_read(case)


@app.get(
    "/v1/review-cases/{case_id}/events",
    response_model=list[ReviewEventRead],
    tags=["review"],
)
def get_review_events(
    case_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]
) -> list[ReviewEventRead]:
    try:
        return ReviewService(session).events(case_id)
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc


@app.get(
    "/v1/review-cases/{case_id}/audit-verification",
    response_model=AuditVerificationRead,
    tags=["review"],
)
def verify_review_audit(
    case_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]
) -> AuditVerificationRead:
    try:
        return ReviewService(session).verify_audit(case_id)
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
