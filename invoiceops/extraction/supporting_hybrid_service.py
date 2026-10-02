"""Durable, opt-in supporting-document fallback with a separate baseline run."""

import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceops.cases.events import append_case_event
from invoiceops.extraction.hybrid.provider import VisionProviderError, VisionProviderSchemaError
from invoiceops.extraction.hybrid.renderer import DocumentRenderingError, PageRenderer
from invoiceops.extraction.service import TextExtractor
from invoiceops.extraction.supporting_hybrid import (
    DELIVERY_PROMPT_VERSION,
    PO_PROMPT_VERSION,
    RECEIPT_PROMPT_VERSION,
    SUPPORTING_HYBRID_NAME,
    SUPPORTING_HYBRID_VERSION,
    SupportingFusion,
    candidate_schema,
    fuse_supporting,
    route_supporting,
)
from invoiceops.extraction.supporting_provider import SupportingVisionProvider
from invoiceops.extraction.supporting_service import SupportingExtractionService
from invoiceops.ingestion.storage import ObjectStore
from invoiceops.models import (
    CaseDocument,
    ModelCallStatus,
    SupportingExtractionRun,
    SupportingModelCall,
)
from invoiceops.observability.metrics import metrics
from invoiceops.schemas.cases import (
    DocumentRole,
    ExtractedGoodsReceipt,
    ExtractedPurchaseOrder,
    SupportingExtractionStatus,
)

ProviderFactory = Callable[[], SupportingVisionProvider]


class HybridSupportingExtractionService:
    def __init__(
        self,
        *,
        session: Session,
        object_store: ObjectStore,
        text_extractor: TextExtractor,
        baseline_service: SupportingExtractionService,
        renderer: PageRenderer,
        provider_factory: ProviderFactory,
        provider_name: str,
        requested_model: str,
    ) -> None:
        self.session = session
        self.object_store = object_store
        self.text_extractor = text_extractor
        self.baseline_service = baseline_service
        self.renderer = renderer
        self.provider_factory = provider_factory
        self.provider_name = provider_name
        self.requested_model = requested_model

    def process(self, attachment: CaseDocument) -> SupportingExtractionRun:
        baseline_run = self.baseline_service.process(attachment)
        if baseline_run.output_json is None:
            raise RuntimeError("successful supporting baseline has no output")
        output_type = (
            ExtractedPurchaseOrder
            if attachment.role == DocumentRole.PURCHASE_ORDER
            else ExtractedGoodsReceipt
        )
        baseline = output_type.model_validate(baseline_run.output_json)
        existing = self._find_run(attachment)
        if existing is not None and existing.status == SupportingExtractionStatus.SUCCEEDED:
            return existing
        body = self.object_store.get(attachment.document.object_key)
        document_text = self.text_extractor.extract(body, attachment.document.content_type)
        routing = route_supporting(baseline, document_text, attachment.role)
        if not routing.invoke_model:
            metrics.add(
                "support_vlm_calls",
                "support_vlm",
                role=attachment.role.value,
                reason="NONE",
                outcome="SKIPPED",
            )
            return baseline_run
        run = self._get_or_create_run(attachment)
        if run.status == SupportingExtractionStatus.SUCCEEDED:
            return run
        prompt_version = {
            DocumentRole.PURCHASE_ORDER: PO_PROMPT_VERSION,
            DocumentRole.GOODS_RECEIPT: RECEIPT_PROMPT_VERSION,
            DocumentRole.DELIVERY_NOTE: DELIVERY_PROMPT_VERSION,
        }[attachment.role]
        reasons = [reason.value for reason in routing.reasons]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "document_hash": attachment.document.sha256,
                    "role": attachment.role.value,
                    "version": SUPPORTING_HYBRID_VERSION,
                    "prompt": prompt_version,
                    "provider": self.provider_name,
                    "model": self.requested_model,
                    "reasons": reasons,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        call = self._get_or_create_call(run, attachment, prompt_version, fingerprint, reasons)
        # Hold the row lock through the provider call. A concurrent delivery waits,
        # then observes the committed outcome instead of spending on a second call.
        locked_call = self.session.scalar(
            select(SupportingModelCall)
            .where(SupportingModelCall.id == call.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_call is None:
            raise RuntimeError("supporting model call disappeared")
        call = locked_call
        output = baseline
        start = time.perf_counter()
        if call.status == ModelCallStatus.SUCCEEDED and call.candidate_json is not None:
            try:
                candidate_type = candidate_schema(attachment.role)
                candidate = candidate_type.model_validate(call.candidate_json)
                output = fuse_supporting(baseline, candidate, document_text).output
            except (ValidationError, ValueError):
                # A damaged replay must never replace the deterministic baseline.
                metrics.add(
                    "support_vlm_calls", "support_vlm",
                    role=attachment.role.value, reason=reasons[0], outcome="FAILED",
                )
        elif call.status == ModelCallStatus.FAILED:
            pass  # Redelivery never spends again for the same failed invocation.
        else:
            try:
                pages = self.renderer.render(body, attachment.document.content_type)
                response = self.provider_factory().extract(attachment.role, pages, document_text)
                candidate_type = candidate_schema(attachment.role)
                candidate = candidate_type.model_validate(response.candidate)
                fused = fuse_supporting(baseline, candidate, document_text)
                output = fused.output
                self._finish_call(
                    call,
                    ModelCallStatus.SUCCEEDED,
                    fused=fused,
                    candidate=candidate.model_dump(mode="json"),
                    returned_model=response.returned_model,
                    response_id=response.response_id,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.total_tokens,
                    latency_ms=response.latency_ms,
                )
                metrics.add(
                    "support_vlm_calls",
                    "support_vlm",
                    role=attachment.role.value,
                    reason=reasons[0],
                    outcome="SUCCEEDED",
                )
                observed_tokens = response.usage.total_tokens
                if (
                    observed_tokens is None
                    and response.usage.input_tokens is not None
                    and response.usage.output_tokens is not None
                ):
                    observed_tokens = (
                        response.usage.input_tokens + response.usage.output_tokens
                    )
                if observed_tokens is not None:
                    metrics.observe(
                        "support_vlm_tokens", float(observed_tokens),
                        "support_vlm", role=attachment.role.value,
                        reason=reasons[0], outcome="SUCCEEDED",
                    )
                for code in fused.grounding.values():
                    if code not in {"GROUNDED_EXACT", "GROUNDED_FUZZY"}:
                        metrics.add(
                            "support_grounding_rejections",
                            "support_vlm",
                            role=attachment.role.value,
                            reason=code,
                        )
            except (
                VisionProviderError,
                DocumentRenderingError,
                ValidationError,
                ValueError,
            ) as exc:
                code = (
                    exc.code
                    if isinstance(exc, (VisionProviderError, DocumentRenderingError))
                    else VisionProviderSchemaError.code
                )
                self._finish_call(call, ModelCallStatus.FAILED, error_code=code)
                metrics.add(
                    "support_vlm_calls",
                    "support_vlm",
                    role=attachment.role.value,
                    reason=reasons[0],
                    outcome="FAILED",
                )
        run.status = SupportingExtractionStatus.SUCCEEDED
        run.output_json = output.model_dump(mode="json")
        run.used_ocr = document_text.used_ocr
        run.latency_ms = round((time.perf_counter() - start) * 1000, 2)
        run.completed_at = datetime.now(UTC)
        append_case_event(
            self.session,
            case_id=attachment.case_id,
            event_key=f"support-hybrid-completed:{run.id}",
            event_type="EXTRACTION_COMPLETED",
            stage="extraction",
            status="completed",
            message="Supporting candidate processing completed; confirmation required",
            document_id=attachment.document_id,
            document_role=attachment.role,
            payload={"extraction_run_id": str(run.id), "confirmation_required": True},
        )
        self.session.commit()
        metrics.observe(
            "support_vlm_duration",
            time.perf_counter() - start,
            "support_vlm",
            role=attachment.role.value,
            outcome=call.status.value,
        )
        return run

    def mark_operational_failure(self, attachment: CaseDocument) -> None:
        self.baseline_service.mark_operational_failure(attachment)

    def _get_or_create_run(self, attachment: CaseDocument) -> SupportingExtractionRun:
        statement = select(SupportingExtractionRun).where(
            SupportingExtractionRun.document_id == attachment.document_id,
            SupportingExtractionRun.role == attachment.role,
            SupportingExtractionRun.extractor_name == SUPPORTING_HYBRID_NAME,
            SupportingExtractionRun.extractor_version == SUPPORTING_HYBRID_VERSION,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            return existing
        run = SupportingExtractionRun(
            document_id=attachment.document_id,
            role=attachment.role,
            extractor_name=SUPPORTING_HYBRID_NAME,
            extractor_version=SUPPORTING_HYBRID_VERSION,
            schema_version="1.0",
            status=SupportingExtractionStatus.PROCESSING,
        )
        self.session.add(run)
        try:
            self.session.commit()
            return run
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(statement)
            if concurrent is None:
                raise
            return concurrent

    def _find_run(self, attachment: CaseDocument) -> SupportingExtractionRun | None:
        return self.session.scalar(
            select(SupportingExtractionRun).where(
                SupportingExtractionRun.document_id == attachment.document_id,
                SupportingExtractionRun.role == attachment.role,
                SupportingExtractionRun.extractor_name == SUPPORTING_HYBRID_NAME,
                SupportingExtractionRun.extractor_version == SUPPORTING_HYBRID_VERSION,
            )
        )

    def _get_or_create_call(
        self,
        run: SupportingExtractionRun,
        attachment: CaseDocument,
        prompt_version: str,
        fingerprint: str,
        reasons: list[str],
    ) -> SupportingModelCall:
        statement = select(SupportingModelCall).where(
            SupportingModelCall.supporting_run_id == run.id,
            SupportingModelCall.prompt_version == prompt_version,
            SupportingModelCall.request_fingerprint == fingerprint,
        )
        existing = self.session.scalar(statement)
        if existing is not None:
            return existing
        call = SupportingModelCall(
            supporting_run_id=run.id,
            role=attachment.role,
            provider=self.provider_name,
            requested_model=self.requested_model,
            prompt_version=prompt_version,
            status=ModelCallStatus.PROCESSING,
            input_document_hash=attachment.document.sha256,
            request_fingerprint=fingerprint,
            routing_json={"reasons": reasons},
        )
        self.session.add(call)
        try:
            self.session.commit()
            return call
        except IntegrityError:
            self.session.rollback()
            concurrent = self.session.scalar(statement)
            if concurrent is None:
                raise
            return concurrent

    def _finish_call(
        self,
        call: SupportingModelCall,
        status: ModelCallStatus,
        *,
        fused: SupportingFusion | None = None,
        candidate: dict[str, object] | None = None,
        returned_model: str | None = None,
        response_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: float | None = None,
        error_code: str | None = None,
    ) -> None:
        call.status = status
        call.candidate_json = candidate
        call.grounding_json = (
            {
                "grounding": fused.grounding,
                "outcomes": {key: value.value for key, value in fused.outcomes.items()},
            }
            if fused is not None
            else None
        )
        call.returned_model = returned_model
        call.provider_response_id = response_id
        call.input_tokens = input_tokens
        call.output_tokens = output_tokens
        call.total_tokens = total_tokens
        call.latency_ms = latency_ms
        call.error_code = error_code
        call.completed_at = datetime.now(UTC)
        self.session.commit()
