import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
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
)
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
)

configure_logging(get_settings().log_level)
logger = logging.getLogger(__name__)
app = FastAPI(title="InvoiceOps API", version="0.1.0")


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
        result = MatchingService(session).match(document_id, command.purchase_order_id)
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
