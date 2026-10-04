import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.openapi.utils import get_openapi
from opentelemetry import trace
from opentelemetry.instrumentation.utils import suppress_instrumentation
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import JSONResponse, Response, StreamingResponse

from apps.api.dependencies import get_dispatcher, get_object_store, get_session_factory
from apps.api.security import authorize_request, get_principal
from invoiceops.auth import Principal
from invoiceops.cases.events import event_to_read as case_event_to_read
from invoiceops.cases.service import (
    CaseConflictError,
    CaseNotFoundError,
    CaseNotReadyError,
    PayableCaseService,
    attachment_to_read,
    case_to_read,
)
from invoiceops.config import Settings, get_settings
from invoiceops.db import engine, get_db
from invoiceops.extraction.selection import (
    current_successful_extraction,
    current_supporting_extraction,
)
from invoiceops.health import dependency_status
from invoiceops.ingestion.dispatch import JobDispatcher
from invoiceops.ingestion.service import (
    DocumentTooLargeError,
    EmptyDocumentError,
    IngestionService,
    UnsupportedDocumentError,
    UploadCommand,
)
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.jobs.events import TERMINAL_EVENT_TYPES, event_to_read, list_job_events
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
    CaseEvent,
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    IngestionJob,
    JobStatus,
    MatchRun,
    ModelCall,
    ModelCallStatus,
    PurchaseOrder,
    ReviewCase,
    ThreeWayContext,
)
from invoiceops.observability.context import (
    request_id_or_new,
    reset_request_id,
    set_request_id,
)
from invoiceops.observability.metrics import metrics
from invoiceops.observability.setup import setup_observability
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
from invoiceops.schemas.auth import PrincipalRead
from invoiceops.schemas.cases import (
    CaseAttachmentAccepted,
    CaseCreate,
    CaseDocumentRead,
    CaseExtractionRead,
    CaseMatchCommand,
    CaseRead,
    ConfirmationRead,
    DocumentRole,
    PurchaseOrderConfirmation,
    ReceiptConfirmation,
)
from invoiceops.schemas.console import DashboardSummary, InvoiceSummary, InvoiceSummaryPage
from invoiceops.schemas.extraction import Invoice
from invoiceops.schemas.extraction_api import (
    ExtractionPendingRead,
    ExtractionResultRead,
    ExtractorMetadata,
    HybridMetadata,
)
from invoiceops.schemas.jobs import ErrorBody, JobEventType, JobRead, UploadAccepted
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
_auth_settings = get_settings()
app = FastAPI(
    title="InvoiceOps API",
    version="0.1.0",
    dependencies=[Depends(authorize_request)],
    openapi_url=None if _auth_settings.auth_mode == "oidc" else "/openapi.json",
    docs_url=None if _auth_settings.auth_mode == "oidc" else "/docs",
    redoc_url=None if _auth_settings.auth_mode == "oidc" else "/redoc",
)
setup_observability(
    get_settings(), service_name=get_settings().otel_service_name, app=app, engine=engine
)


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
    settings = get_settings()
    request_id = request_id_or_new(request.headers.get(settings.request_id_header))
    token = set_request_id(request_id)
    started = time.perf_counter()
    is_health = request.url.path in {"/health/live", "/health/ready", "/healthz"}
    # FastAPIInstrumentor owns the SERVER span. This middleware adds only safe
    # route/status attributes, correlation IDs, logs, and bounded custom metrics.
    trace_scope = nullcontext(None if is_health else trace.get_current_span())
    try:
        with trace_scope as request_span:
            if request_span is not None:
                # Request IDs are validated, bounded correlation values. They are
                # intentionally span attributes, never metric labels.
                request_span.set_attribute("invoiceops.request_id", request_id)
            try:
                response = await call_next(request)
            except Exception as exc:
                route_template = _route_template(request)
                if request_span is not None:
                    request_span.update_name(f"{request.method} {route_template}")
                    request_span.set_attribute("http.route", route_template)
                method = _metric_method(request.method)
                if not is_health:
                    labels = {
                        "method": method,
                        "route": route_template,
                        "status_class": "5xx",
                    }
                    metrics.add("http_requests", "http", **labels)
                    metrics.observe(
                        "http_duration",
                        time.perf_counter() - started,
                        "http",
                        **labels,
                    )
                logger.error(
                    "HTTP request failed",
                    extra={
                        "event": "http.request_failed",
                        "request_method": request.method,
                        "route_template": route_template,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "error_type": type(exc).__name__,
                    },
                )
                raise
            response.headers[settings.request_id_header] = request_id
            route_template = _route_template(request)
            if request_span is not None:
                request_span.update_name(f"{request.method} {route_template}")
                request_span.set_attribute("http.route", route_template)
                request_span.set_attribute("http.response.status_code", response.status_code)
            if not is_health:
                method = _metric_method(request.method)
                labels = {
                    "method": method,
                    "route": route_template,
                    "status_class": f"{response.status_code // 100}xx",
                }
                metrics.add("http_requests", "http", **labels)
                metrics.observe("http_duration", time.perf_counter() - started, "http", **labels)
                logger.info(
                    "HTTP request completed",
                    extra={
                        "event": "http.request_completed",
                        "request_method": request.method,
                        "route_template": route_template,
                        "status_code": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
            return response
    finally:
        reset_request_id(token)


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def _metric_method(method: str) -> str:
    return method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "OTHER"


@app.get("/health/live", tags=["operations"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/healthz", tags=["operations"], deprecated=True)
def health_compatibility() -> dict[str, str]:
    return health_live()


@app.get("/health/ready", tags=["operations"])
def health_ready(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    with suppress_instrumentation():
        return _readiness_response(settings)


def _readiness_response(settings: Settings) -> Response:
    components = dependency_status(settings)
    ready = all(value == "ready" for value in components.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content=(
            {"status": "ready" if ready else "unavailable"}
            if settings.auth_mode == "oidc"
            else {"status": "ready" if ready else "unavailable", "components": components}
        ),
    )


@app.get("/v1/me", response_model=PrincipalRead, tags=["identity"])
def who_am_i(principal: Annotated[Principal, Depends(get_principal)]) -> PrincipalRead:
    return PrincipalRead(subject=principal.subject, roles=sorted(principal.roles))


def _case_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CaseNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "CASE_NOT_FOUND", "message": "Payable case not found"},
        )
    if isinstance(exc, CaseConflictError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, CaseNotReadyError):
        return HTTPException(
            status_code=409,
            detail={"code": "CASE_NOT_READY", "message": str(exc)},
        )
    raise exc


@app.post("/v1/cases", response_model=CaseRead, status_code=201, tags=["cases"])
def create_payable_case(
    command: CaseCreate,
    session: Annotated[Session, Depends(get_db)],
) -> CaseRead:
    try:
        result = PayableCaseService(session).create(command)
    except (CaseConflictError, CaseNotFoundError, CaseNotReadyError) as exc:
        raise _case_http_error(exc) from exc
    return case_to_read(result.payable_case)


@app.get("/v1/cases/{case_id}", response_model=CaseRead, tags=["cases"])
def get_payable_case(
    case_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> CaseRead:
    try:
        return case_to_read(PayableCaseService(session).get(case_id))
    except CaseNotFoundError as exc:
        raise _case_http_error(exc) from exc


@app.post(
    "/v1/cases/{case_id}/documents",
    response_model=CaseAttachmentAccepted,
    status_code=202,
    tags=["cases"],
)
def attach_case_document(
    case_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="PDF, JPEG, or PNG evidence")],
    role: Annotated[DocumentRole, Form()],
    idempotency_key: Annotated[str, Form(min_length=1, max_length=200)],
    expected_case_version: Annotated[int, Form(ge=1)],
    session: Annotated[Session, Depends(get_db)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
    dispatcher: Annotated[JobDispatcher, Depends(get_dispatcher)],
    settings: Annotated[Settings, Depends(get_settings)],
    supersedes_id: Annotated[uuid.UUID | None, Form()] = None,
) -> CaseAttachmentAccepted:
    body = file.file.read(settings.max_upload_bytes + 1)
    service = PayableCaseService(
        session,
        object_store=object_store,
        dispatcher=dispatcher,
        max_upload_bytes=settings.max_upload_bytes,
    )
    try:
        return service.attach(
            case_id,
            role=role,
            idempotency_key=idempotency_key,
            expected_case_version=expected_case_version,
            supersedes_id=supersedes_id,
            command=UploadCommand(
                filename=file.filename or "upload",
                content_type=file.content_type or "application/octet-stream",
                body=body,
            ),
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=415,
            detail={"code": "UNSUPPORTED_DOCUMENT", "message": str(exc)},
        ) from exc
    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_DOCUMENT", "message": "The uploaded file is empty"},
        ) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "DOCUMENT_TOO_LARGE", "message": "The uploaded file is too large"},
        ) from exc
    except (CaseConflictError, CaseNotFoundError, CaseNotReadyError) as exc:
        raise _case_http_error(exc) from exc


@app.get(
    "/v1/cases/{case_id}/documents",
    response_model=list[CaseDocumentRead],
    tags=["cases"],
)
def list_case_documents(
    case_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> list[CaseDocumentRead]:
    service = PayableCaseService(session)
    try:
        return [attachment_to_read(session, item) for item in service.list_documents(case_id)]
    except CaseNotFoundError as exc:
        raise _case_http_error(exc) from exc


@app.get(
    "/v1/cases/{case_id}/extractions",
    response_model=list[CaseExtractionRead],
    tags=["cases"],
)
def list_case_extractions(
    case_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> list[CaseExtractionRead]:
    service = PayableCaseService(session)
    try:
        attachments = service.list_documents(case_id)
    except CaseNotFoundError as exc:
        raise _case_http_error(exc) from exc
    result: list[CaseExtractionRead] = []
    for attachment in attachments:
        if attachment.role == DocumentRole.INVOICE:
            invoice_run = current_successful_extraction(session, attachment.document_id)
            if invoice_run is not None:
                result.append(
                    CaseExtractionRead(
                        id=invoice_run.id,
                        document_id=invoice_run.document_id,
                        role=attachment.role,
                        extractor_name=invoice_run.extractor_name,
                        extractor_version=invoice_run.extractor_version,
                        schema_version=invoice_run.schema_version,
                        status=invoice_run.status.value,
                        output=invoice_run.output_json,
                        used_ocr=invoice_run.used_ocr,
                        latency_ms=invoice_run.latency_ms,
                        error_code=invoice_run.error_code,
                        created_at=invoice_run.created_at,
                        completed_at=invoice_run.completed_at,
                    )
                )
            continue
        supporting_run = current_supporting_extraction(
            session, attachment.document_id, attachment.role
        )
        if supporting_run is not None:
            result.append(
                CaseExtractionRead(
                    id=supporting_run.id,
                    document_id=supporting_run.document_id,
                    role=supporting_run.role,
                    extractor_name=supporting_run.extractor_name,
                    extractor_version=supporting_run.extractor_version,
                    schema_version=supporting_run.schema_version,
                    status=supporting_run.status.value,
                    output=supporting_run.output_json,
                    used_ocr=supporting_run.used_ocr,
                    latency_ms=supporting_run.latency_ms,
                    error_code=supporting_run.error_code,
                    created_at=supporting_run.created_at,
                    completed_at=supporting_run.completed_at,
                )
            )
    return result


@app.get(
    "/v1/cases/{case_id}/events",
    response_class=StreamingResponse,
    tags=["cases"],
)
async def stream_case_events(
    case_id: uuid.UUID,
    request: Request,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    with session_factory() as initial_session:
        try:
            PayableCaseService(initial_session).get(case_id)
        except CaseNotFoundError as exc:
            raise _case_http_error(exc) from exc
    starting_sequence = _last_event_sequence(last_event_id)

    async def generate() -> AsyncIterator[str]:
        sequence = starting_sequence
        heartbeat_due = time.monotonic() + settings.sse_heartbeat_seconds
        while True:
            if await request.is_disconnected():
                return
            with session_factory() as event_session:
                events = list(
                    event_session.scalars(
                        select(CaseEvent)
                        .where(
                            CaseEvent.case_id == case_id,
                            CaseEvent.sequence_number > sequence,
                        )
                        .order_by(CaseEvent.sequence_number)
                        .limit(settings.sse_batch_size)
                    )
                )
            for event in events:
                read = case_event_to_read(event)
                sequence = event.sequence_number
                yield _sse_message(
                    event=event.event_type,
                    event_id=sequence,
                    data=read.model_dump_json(),
                )
            now = time.monotonic()
            if now >= heartbeat_due:
                yield _sse_message(event="heartbeat", data="{}")
                heartbeat_due = now + settings.sse_heartbeat_seconds
            await asyncio.sleep(settings.sse_poll_interval_seconds)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post(
    "/v1/cases/{case_id}/purchase-order/confirm",
    response_model=ConfirmationRead,
    tags=["cases"],
)
def confirm_case_purchase_order(
    case_id: uuid.UUID,
    command: PurchaseOrderConfirmation,
    session: Annotated[Session, Depends(get_db)],
) -> ConfirmationRead:
    try:
        return PayableCaseService(session).confirm_purchase_order(case_id, command)
    except (CaseConflictError, CaseNotFoundError, CaseNotReadyError) as exc:
        raise _case_http_error(exc) from exc


@app.post(
    "/v1/cases/{case_id}/receipts/{document_id}/confirm",
    response_model=ConfirmationRead,
    tags=["cases"],
)
def confirm_case_receipt(
    case_id: uuid.UUID,
    document_id: uuid.UUID,
    command: ReceiptConfirmation,
    session: Annotated[Session, Depends(get_db)],
) -> ConfirmationRead:
    try:
        return PayableCaseService(session).confirm_receipt(case_id, document_id, command)
    except (CaseConflictError, CaseNotFoundError, CaseNotReadyError) as exc:
        raise _case_http_error(exc) from exc


@app.post("/v1/cases/{case_id}/match", response_model=MatchRunRead, tags=["cases"])
def match_payable_case(
    case_id: uuid.UUID,
    command: CaseMatchCommand,
    session: Annotated[Session, Depends(get_db)],
) -> MatchRunRead:
    try:
        return match_run_to_read(PayableCaseService(session).match(case_id, command))
    except (CaseConflictError, CaseNotFoundError, CaseNotReadyError) as exc:
        raise _case_http_error(exc) from exc


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
        events_url=str(request.url_for("stream_job_events", job_id=str(result.job.id))),
        extraction_url=str(
            request.url_for("get_extraction", document_id=str(result.job.document_id))
        ),
        deduplicated=not result.created,
    )


def _field_value(output: dict[str, object] | None, name: str) -> object | None:
    if output is None:
        return None
    field = output.get(name)
    return field.get("value") if isinstance(field, dict) else None


def _invoice_summary(session: Session, document: Document) -> InvoiceSummary:
    extraction = current_successful_extraction(session, document.id)
    output = extraction.output_json if extraction is not None else None
    match_run = session.scalar(
        select(MatchRun)
        .where(MatchRun.document_id == document.id)
        .order_by(MatchRun.created_at.desc(), MatchRun.id.desc())
        .limit(1)
    )
    review_case = match_run.review_case if match_run is not None else None
    return InvoiceSummary(
        document_id=document.id,
        filename=document.original_filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        created_at=document.created_at,
        job_id=document.job.id,
        job_status=document.job.status,
        invoice_number=_field_value(output, "invoice_number"),
        currency=_field_value(output, "currency"),
        total=_field_value(output, "total"),
        latest_match_run_id=match_run.id if match_run is not None else None,
        match_decision=match_run.decision if match_run is not None else None,
        review_case_id=review_case.id if review_case is not None else None,
        review_status=review_case.status if review_case is not None else None,
    )


@app.get("/v1/invoices", response_model=InvoiceSummaryPage, tags=["invoices"])
def list_invoices(
    session: Annotated[Session, Depends(get_db)],
    cursor: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> InvoiceSummaryPage:
    statement = select(Document).order_by(Document.created_at.desc(), Document.id.desc())
    if cursor is not None:
        cursor_document = session.get(Document, cursor)
        if cursor_document is None:
            raise HTTPException(status_code=400, detail="Invalid invoice cursor")
        statement = statement.where(
            (Document.created_at < cursor_document.created_at)
            | (
                (Document.created_at == cursor_document.created_at)
                & (Document.id < cursor_document.id)
            )
        )
    documents = list(session.scalars(statement.limit(limit + 1)))
    page_documents = documents[:limit]
    return InvoiceSummaryPage(
        items=[_invoice_summary(session, document) for document in page_documents],
        next_cursor=page_documents[-1].id if len(documents) > limit else None,
    )


@app.get("/v1/invoices/{document_id}", response_model=InvoiceSummary, tags=["invoices"])
def get_invoice_summary(
    document_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
) -> InvoiceSummary:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_summary(session, document)


@app.get("/v1/documents/{document_id}/content", tags=["invoices"])
def get_document_content(
    document_id: uuid.UUID,
    session: Annotated[Session, Depends(get_db)],
    object_store: Annotated[ObjectStore, Depends(get_object_store)],
) -> Response:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        body = object_store.get(document.object_key)
    except Exception as exc:
        logger.error(
            "Stored document could not be retrieved",
            extra={
                "event": "document.retrieve_failed",
                "document_id": str(document_id),
                "error_type": type(exc).__name__,
            },
        )
        raise HTTPException(status_code=503, detail="Document is temporarily unavailable") from exc
    return Response(
        content=body,
        media_type=document.content_type,
        headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline"},
    )


@app.get("/v1/dashboard/summary", response_model=DashboardSummary, tags=["dashboard"])
def get_dashboard_summary(
    session: Annotated[Session, Depends(get_db)],
) -> DashboardSummary:
    waiting_statuses = (ReviewStatus.OPEN, ReviewStatus.CLAIMED)
    return DashboardSummary(
        documents_total=session.scalar(select(func.count(Document.id))) or 0,
        jobs_processing=session.scalar(
            select(func.count(IngestionJob.id)).where(
                IngestionJob.status.in_((JobStatus.QUEUED, JobStatus.PROCESSING))
            )
        )
        or 0,
        jobs_failed=session.scalar(
            select(func.count(IngestionJob.id)).where(IngestionJob.status == JobStatus.FAILED)
        )
        or 0,
        reviews_waiting=session.scalar(
            select(func.count(ReviewCase.id)).where(ReviewCase.status.in_(waiting_statuses))
        )
        or 0,
        oldest_waiting_review_opened_at=session.scalar(
            select(func.min(ReviewCase.opened_at)).where(ReviewCase.status.in_(waiting_statuses))
        ),
    )


@app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _last_event_sequence(value: str | None) -> int:
    if value is None or not value.strip():
        return 0
    try:
        sequence = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
    if sequence < 0:
        raise HTTPException(status_code=400, detail="Last-Event-ID must not be negative")
    return sequence


def _sse_message(*, event: str, data: str, event_id: int | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.insert(0, f"id: {event_id}")
    lines.extend(f"data: {line}" for line in data.splitlines() or [""])
    return "\n".join(lines) + "\n\n"


@app.get(
    "/v1/jobs/{job_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {}},
            "description": "Durable processing events followed by heartbeats until terminal state",
        }
    },
    tags=["jobs"],
)
async def stream_job_events(
    job_id: uuid.UUID,
    request: Request,
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    with session_factory() as initial_session:
        if initial_session.get(IngestionJob, job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
    starting_sequence = _last_event_sequence(last_event_id)

    async def generate() -> AsyncIterator[str]:
        sequence = starting_sequence
        heartbeat_due = time.monotonic() + settings.sse_heartbeat_seconds
        while True:
            if await request.is_disconnected():
                return
            with suppress_instrumentation():
                with session_factory() as event_session:
                    events = list_job_events(
                        event_session,
                        job_id,
                        after_sequence=sequence,
                        limit=settings.sse_batch_size,
                    )
                    job = event_session.get(IngestionJob, job_id)
                    terminal_status = job.status if job is not None else None
                    serialized = [event_to_read(event) for event in events]
            for event in serialized:
                sequence = event.sequence
                yield _sse_message(
                    event=event.event_type.value,
                    event_id=event.sequence,
                    data=event.model_dump_json(),
                )
                if event.event_type in TERMINAL_EVENT_TYPES:
                    return
            if terminal_status in {JobStatus.SUCCEEDED, JobStatus.FAILED} and not serialized:
                return
            now = time.monotonic()
            if now >= heartbeat_due:
                heartbeat = {
                    "job_id": str(job_id),
                    "event_type": JobEventType.HEARTBEAT.value,
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
                yield _sse_message(
                    event=JobEventType.HEARTBEAT.value,
                    data=json.dumps(heartbeat, separators=(",", ":")),
                )
                heartbeat_due = now + settings.sse_heartbeat_seconds
            await asyncio.sleep(settings.sse_poll_interval_seconds)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
    "/v1/purchase-orders",
    response_model=list[PurchaseOrderRead],
    tags=["purchase-orders"],
)
def list_purchase_orders(
    session: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[PurchaseOrderRead]:
    purchase_orders = session.scalars(
        select(PurchaseOrder)
        .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        .limit(limit)
    )
    return [purchase_order_to_read(purchase_order) for purchase_order in purchase_orders]


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
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_db)],
) -> GoodsReceiptRead:
    try:
        receipt = GoodsReceiptService(session).reverse(
            receipt_id, principal.subject, command.reason,
            actor_roles=tuple(sorted(role.value for role in principal.roles)),
        )
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
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).claim(
            case_id, principal.subject, command.expected_version,
            actor_roles=tuple(sorted(role.value for role in principal.roles)),
        )
    except ReviewCaseNotFoundError as exc:
        raise review_not_found() from exc
    except ReviewTransitionError as exc:
        raise review_conflict(exc) from exc
    return review_case_to_read(case)


@app.post("/v1/review-cases/{case_id}/release", response_model=ReviewCaseRead, tags=["review"])
def release_review_case(
    case_id: uuid.UUID,
    command: ReleaseCommand,
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).release(
            case_id, principal.subject, command.expected_version, command.reason,
            actor_roles=tuple(sorted(role.value for role in principal.roles)),
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
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).comment(
            case_id, principal.subject, command.expected_version, command.comment,
            actor_roles=tuple(sorted(role.value for role in principal.roles)),
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
    principal: Annotated[Principal, Depends(get_principal)],
    session: Annotated[Session, Depends(get_db)],
) -> ReviewCaseRead:
    try:
        case = ReviewService(session).resolve(
            case_id,
            principal.subject,
            command.expected_version,
            command.resolution,
            command.reason,
            actor_roles=tuple(sorted(role.value for role in principal.roles)),
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


def _secured_openapi() -> dict[str, Any]:
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    components = schema.setdefault("components", {})
    components.setdefault("securitySchemes", {})["BearerAuth"] = {
        "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
    }
    for path, operations in schema.get("paths", {}).items():
        if path.startswith("/v1/"):
            for operation in operations.values():
                if isinstance(operation, dict):
                    operation["security"] = [{"BearerAuth": []}]
    app.openapi_schema = schema
    return schema


app.openapi = _secured_openapi  # type: ignore[method-assign]
