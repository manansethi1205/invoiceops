import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session
from starlette.responses import Response

from apps.api.dependencies import get_dispatcher, get_object_store
from invoiceops.config import Settings, get_settings
from invoiceops.db import get_db
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
from invoiceops.models import IngestionJob
from invoiceops.schemas.jobs import ErrorBody, JobRead, UploadAccepted

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
    except Exception:
        logger.exception(
            "HTTP request failed",
            extra={
                "event": "http.request_failed",
                "request_method": request.method,
                "request_path": request.url.path,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
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
        status=result.job.status,
        status_url=str(request.url_for("get_job", job_id=str(result.job.id))),
        deduplicated=not result.created,
    )


@app.get("/v1/jobs/{job_id}", response_model=JobRead, tags=["jobs"])
def get_job(job_id: uuid.UUID, session: Annotated[Session, Depends(get_db)]) -> IngestionJob:
    job = session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
