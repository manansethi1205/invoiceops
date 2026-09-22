import hashlib
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceops.extraction.errors import DocumentExtractionError
from invoiceops.extraction.failures import extraction_error_code, safe_extraction_error_message
from invoiceops.extraction.hybrid.fusion import FusionResult, fuse_invoice
from invoiceops.extraction.hybrid.provider import (
    VisionExtractionProvider,
    VisionProviderError,
)
from invoiceops.extraction.hybrid.renderer import DocumentRenderingError, PageRenderer
from invoiceops.extraction.hybrid.router import route_extraction
from invoiceops.extraction.hybrid.schemas import VisionInvoiceCandidate
from invoiceops.extraction.service import ExtractionService, TextExtractor
from invoiceops.extraction.version import (
    HYBRID_EXTRACTOR_NAME,
    HYBRID_EXTRACTOR_VERSION,
    SCHEMA_VERSION,
)
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.models import (
    Document,
    ExtractionRun,
    ExtractionRunStatus,
    ModelCall,
    ModelCallStatus,
)
from invoiceops.schemas.extraction import Invoice

ProviderFactory = Callable[[], VisionExtractionProvider]


class HybridExtractionService:
    """Persist baseline first, then optionally create a separately versioned hybrid result."""

    def __init__(
        self,
        *,
        session: Session,
        object_store: ObjectStore,
        text_extractor: TextExtractor,
        baseline_service: ExtractionService,
        renderer: PageRenderer,
        provider_factory: ProviderFactory,
        provider_name: str,
        requested_model: str,
        prompt_version: str,
        fuzzy_threshold: float = 92.0,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.text_extractor = text_extractor
        self.baseline_service = baseline_service
        self.renderer = renderer
        self.provider_factory = provider_factory
        self.provider_name = provider_name
        self.requested_model = requested_model
        self.prompt_version = prompt_version
        self.fuzzy_threshold = fuzzy_threshold

    def process(self, document: Document) -> ExtractionRun:
        started = time.perf_counter()
        baseline_run = self.baseline_service.process(document)
        baseline = Invoice.model_validate(baseline_run.output_json)
        run = self._get_or_create_run(document.id)
        if run.status == ExtractionRunStatus.SUCCEEDED:
            return run
        run = self._mark_processing(run)
        try:
            body = self.object_store.get(document.object_key)
            document_text = self.text_extractor.extract(body, document.content_type)
        except (DocumentExtractionError, ValidationError) as exc:
            self._mark_terminal_failure(run.id, exc)
            raise

        routing = route_extraction(baseline, document_text)
        fingerprint = self._fingerprint(document.sha256, routing.model_dump(mode="json"))
        model_call = self._get_or_create_call(run.id, fingerprint, routing.model_dump(mode="json"))
        invoice = baseline
        summary: dict[str, object] = {"grounding": {}, "fusion": {}}

        if not routing.invoke_vlm:
            self._finish_call(model_call.id, status=ModelCallStatus.SKIPPED, summary=summary)
        elif model_call.status == ModelCallStatus.SUCCEEDED and model_call.candidate_json:
            candidate = VisionInvoiceCandidate.model_validate(model_call.candidate_json)
            fused = fuse_invoice(
                baseline, candidate, document_text, fuzzy_threshold=self.fuzzy_threshold
            )
            invoice = fused.invoice
            summary = self._summary(fused)
        elif model_call.status == ModelCallStatus.FAILED:
            pass
        else:
            try:
                pages = self.renderer.render(body, document.content_type)
                provider = self.provider_factory()
                provider_response = provider.extract(pages, document_text)
                fused = fuse_invoice(
                    baseline,
                    provider_response.candidate,
                    document_text,
                    fuzzy_threshold=self.fuzzy_threshold,
                )
                invoice = fused.invoice
                summary = self._summary(fused)
                self._finish_call(
                    model_call.id,
                    status=ModelCallStatus.SUCCEEDED,
                    response_id=provider_response.response_id,
                    returned_model=provider_response.returned_model,
                    input_tokens=provider_response.usage.input_tokens,
                    output_tokens=provider_response.usage.output_tokens,
                    total_tokens=provider_response.usage.total_tokens,
                    latency_ms=provider_response.latency_ms,
                    candidate=provider_response.candidate.model_dump(mode="json"),
                    summary=summary,
                )
            except (VisionProviderError, DocumentRenderingError) as exc:
                self._finish_call(
                    model_call.id,
                    status=ModelCallStatus.FAILED,
                    error_code=exc.code,
                    summary=summary,
                )

        self.session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.id == run.id)
            .values(
                status=ExtractionRunStatus.SUCCEEDED,
                output_json=invoice.model_dump(mode="json"),
                used_ocr=document_text.used_ocr,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error_code=None,
                error_message=None,
                completed_at=datetime.now(UTC),
            )
        )
        self.session.commit()
        return self._require_run(run.id)

    def _fingerprint(self, document_sha256: str, routing: dict[str, object]) -> str:
        payload = {
            "document_sha256": document_sha256,
            "extractor": f"{HYBRID_EXTRACTOR_NAME}@{HYBRID_EXTRACTOR_VERSION}",
            "provider": self.provider_name,
            "model": self.requested_model,
            "prompt_version": self.prompt_version,
            "routing": routing,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def _get_or_create_run(self, document_id: uuid.UUID) -> ExtractionRun:
        existing = self._find_run(document_id)
        if existing is not None:
            return existing
        run = ExtractionRun(
            document_id=document_id,
            extractor_name=HYBRID_EXTRACTOR_NAME,
            extractor_version=HYBRID_EXTRACTOR_VERSION,
            schema_version=SCHEMA_VERSION,
            status=ExtractionRunStatus.PROCESSING,
        )
        self.session.add(run)
        try:
            self.session.commit()
            return run
        except IntegrityError:
            self.session.rollback()
            concurrent = self._find_run(document_id)
            if concurrent is None:
                raise
            return concurrent

    def _find_run(self, document_id: uuid.UUID) -> ExtractionRun | None:
        return self.session.scalar(
            select(ExtractionRun).where(
                ExtractionRun.document_id == document_id,
                ExtractionRun.extractor_name == HYBRID_EXTRACTOR_NAME,
                ExtractionRun.extractor_version == HYBRID_EXTRACTOR_VERSION,
            )
        )

    def _mark_processing(self, run: ExtractionRun) -> ExtractionRun:
        if run.status == ExtractionRunStatus.PROCESSING:
            return run
        self.session.execute(
            update(ExtractionRun)
            .where(
                ExtractionRun.id == run.id,
                ExtractionRun.status != ExtractionRunStatus.SUCCEEDED,
            )
            .values(
                status=ExtractionRunStatus.PROCESSING,
                output_json=None,
                completed_at=None,
                error_code=None,
                error_message=None,
            )
        )
        self.session.commit()
        self.session.refresh(run)
        return run

    def _get_or_create_call(
        self, run_id: uuid.UUID, fingerprint: str, routing: dict[str, object]
    ) -> ModelCall:
        existing = self.session.scalar(
            select(ModelCall).where(
                ModelCall.extraction_run_id == run_id,
                ModelCall.prompt_version == self.prompt_version,
                ModelCall.request_fingerprint == fingerprint,
            )
        )
        if existing is not None:
            return existing
        call = ModelCall(
            extraction_run_id=run_id,
            provider=self.provider_name,
            requested_model=self.requested_model,
            prompt_version=self.prompt_version,
            status=ModelCallStatus.PROCESSING,
            request_fingerprint=fingerprint,
            routing_json=routing,
        )
        self.session.add(call)
        try:
            self.session.commit()
            return call
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(
                select(ModelCall).where(
                    ModelCall.extraction_run_id == run_id,
                    ModelCall.prompt_version == self.prompt_version,
                    ModelCall.request_fingerprint == fingerprint,
                )
            )
            if concurrent is None:
                raise
            return concurrent

    def _finish_call(
        self,
        call_id: uuid.UUID,
        *,
        status: ModelCallStatus,
        summary: dict[str, object],
        response_id: str | None = None,
        returned_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        candidate: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        self.session.execute(
            update(ModelCall)
            .where(ModelCall.id == call_id, ModelCall.status != ModelCallStatus.SUCCEEDED)
            .values(
                status=status,
                returned_model=returned_model,
                provider_response_id=response_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
                candidate_json=candidate,
                grounding_fusion_json=summary,
                error_code=error_code,
                completed_at=datetime.now(UTC),
            )
        )
        self.session.commit()

    @staticmethod
    def _summary(fused: FusionResult) -> dict[str, object]:
        return {
            "grounding": dict(fused.grounding),
            "fusion": {key: value.value for key, value in fused.outcomes.items()},
        }

    def _mark_terminal_failure(
        self, run_id: uuid.UUID, exc: DocumentExtractionError | ValidationError
    ) -> None:
        self.session.execute(
            update(ExtractionRun)
            .where(ExtractionRun.id == run_id)
            .values(
                status=ExtractionRunStatus.FAILED,
                error_code=extraction_error_code(exc),
                error_message=safe_extraction_error_message(exc),
                completed_at=datetime.now(UTC),
            )
        )
        self.session.commit()

    def _require_run(self, run_id: uuid.UUID) -> ExtractionRun:
        run = self.session.get(ExtractionRun, run_id)
        if run is None:
            raise RuntimeError("hybrid extraction run disappeared after commit")
        self.session.refresh(run)
        return run
