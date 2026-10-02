from sqlalchemy.orm import Session

from invoiceops.config import get_settings
from invoiceops.extraction.hybrid.provider import (
    FakeVisionExtractionProvider,
    OpenAIVisionExtractionProvider,
    ReplayVisionExtractionProvider,
    VisionExtractionProvider,
)
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.hybrid.service import HybridExtractionService
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.service import ExtractionService
from invoiceops.extraction.supporting_hybrid_service import HybridSupportingExtractionService
from invoiceops.extraction.supporting_provider import (
    FakeSupportingVisionProvider,
    OpenAISupportingVisionProvider,
    ReplaySupportingVisionProvider,
    SupportingVisionProvider,
)
from invoiceops.extraction.supporting_service import SupportingExtractionService
from invoiceops.ingestion.storage import S3ObjectStore
from invoiceops.observability.tracing import span


def build_supporting_extraction_service(
    session: Session,
) -> SupportingExtractionService | HybridSupportingExtractionService:
    settings = get_settings()
    store = S3ObjectStore(settings)
    text_extractor = DocumentTextExtractor(
        stage_context=lambda stage: span(f"supporting_extraction.{stage}")
    )
    baseline = SupportingExtractionService(
        session=session,
        object_store=store,
        text_extractor=text_extractor,
    )
    if not settings.supporting_vlm_enabled:
        return baseline

    def provider_factory() -> SupportingVisionProvider:
        if settings.supporting_vlm_provider == "fake":
            return FakeSupportingVisionProvider()
        if settings.supporting_vlm_provider == "replay":
            return ReplaySupportingVisionProvider([])
        api_key = settings.openai_api_key
        if api_key is None:
            raise ValueError("supporting provider credentials are not configured")
        return OpenAISupportingVisionProvider(
            api_key=api_key.get_secret_value(),
            model=settings.supporting_vlm_model,
            timeout_seconds=settings.vlm_timeout_seconds,
            image_detail=settings.vlm_image_detail,
        )

    return HybridSupportingExtractionService(
        session=session,
        object_store=store,
        text_extractor=text_extractor,
        baseline_service=baseline,
        renderer=PageRenderer(
            dpi=settings.vlm_render_dpi,
            max_dimension=settings.vlm_max_image_dimension,
            max_pages=settings.vlm_max_pages,
        ),
        provider_factory=provider_factory,
        provider_name=settings.supporting_vlm_provider,
        requested_model=settings.supporting_vlm_model,
    )


def build_extraction_service(session: Session) -> ExtractionService | HybridExtractionService:
    settings = get_settings()
    store = S3ObjectStore(settings)
    text_extractor = DocumentTextExtractor(stage_context=lambda stage: span(f"extraction.{stage}"))
    baseline = ExtractionService(
        session=session,
        object_store=store,
        text_extractor=text_extractor,
        invoice_extractor=DeterministicInvoiceExtractor(),
    )
    if not settings.vlm_enabled:
        return baseline

    def provider_factory() -> VisionExtractionProvider:
        if settings.vlm_provider == "fake":
            return FakeVisionExtractionProvider()
        if settings.vlm_provider == "replay":
            return ReplayVisionExtractionProvider([])
        api_key = settings.openai_api_key
        if api_key is None:
            raise ValueError("OpenAI credentials are not configured")
        return OpenAIVisionExtractionProvider(
            api_key=api_key.get_secret_value(),
            model=settings.vlm_model,
            timeout_seconds=settings.vlm_timeout_seconds,
            max_retries=settings.vlm_max_retries,
            image_detail=settings.vlm_image_detail,
        )

    return HybridExtractionService(
        session=session,
        object_store=store,
        text_extractor=text_extractor,
        baseline_service=baseline,
        renderer=PageRenderer(
            dpi=settings.vlm_render_dpi,
            max_dimension=settings.vlm_max_image_dimension,
            max_pages=settings.vlm_max_pages,
        ),
        provider_factory=provider_factory,
        provider_name=settings.vlm_provider,
        requested_model=settings.vlm_model,
        prompt_version=settings.vlm_prompt_version,
        fuzzy_threshold=settings.vlm_fuzzy_grounding_threshold,
    )
