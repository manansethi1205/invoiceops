from types import SimpleNamespace

import pymupdf
import pytest
from pydantic import ValidationError

from invoiceops.extraction.hybrid import provider as provider_module
from invoiceops.extraction.hybrid.provider import (
    OpenAIVisionExtractionProvider,
    VisionProviderIncompleteError,
    VisionProviderRefusalError,
    VisionProviderSchemaError,
    VisionProviderTransientError,
)
from invoiceops.extraction.hybrid.renderer import (
    DocumentRenderingError,
    PageLimitExceededError,
    PageRenderer,
)
from invoiceops.extraction.hybrid.schemas import (
    CandidateField,
    RenderedPage,
    VisionInvoiceCandidate,
)
from invoiceops.schemas.extraction import DocumentText


def missing() -> CandidateField:
    return CandidateField(raw_value=None, page=None, evidence_quote=None, confidence=None)


def valid_candidate() -> VisionInvoiceCandidate:
    return VisionInvoiceCandidate(
        invoice_number=missing(),
        invoice_date=missing(),
        currency=missing(),
        subtotal=missing(),
        tax=missing(),
        total=missing(),
        line_items=[],
    )


def rendered_page() -> RenderedPage:
    return RenderedPage(page=0, mime_type="image/png", width=1, height=1, image_bytes=b"png")


class Responses:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(outcomes: list[object]) -> SimpleNamespace:
    return SimpleNamespace(responses=Responses(outcomes))


def provider(fake_client: object, *, retries: int = 0) -> OpenAIVisionExtractionProvider:
    return OpenAIVisionExtractionProvider(
        api_key="test-key",
        model="test-model",
        timeout_seconds=1,
        max_retries=retries,
        image_detail="low",
        sleeper=lambda _: None,
        client=fake_client,
    )


def test_strict_candidate_schema_rejects_extra_and_invalid_confidence() -> None:
    payload = valid_candidate().model_dump(mode="python")
    payload["extra"] = "no"
    with pytest.raises(ValidationError):
        VisionInvoiceCandidate.model_validate(payload)
    with pytest.raises(ValidationError):
        CandidateField(raw_value="x", page=0, evidence_quote="x", confidence=1.1)


def test_openai_request_uses_images_strict_parse_store_false_and_no_tools() -> None:
    response = SimpleNamespace(
        status="completed",
        output_parsed=valid_candidate(),
        id="resp-1",
        model="returned-model",
        usage=SimpleNamespace(input_tokens=10, output_tokens=4, total_tokens=14),
        output=[],
    )
    fake = client([response])
    result = provider(fake).extract([rendered_page()], DocumentText(pages=[], used_ocr=False))
    call = fake.responses.calls[0]
    assert call["store"] is False
    assert call["tools"] == []
    assert call["text_format"] is VisionInvoiceCandidate
    assert "data:image/png;base64," in str(call["input"])
    assert result.response_id == "resp-1"
    assert result.usage.total_tokens == 14


def test_provider_handles_refusal_incomplete_malformed_and_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = SimpleNamespace(
        status="completed",
        output_parsed=None,
        output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
    )
    with pytest.raises(VisionProviderRefusalError):
        provider(client([refusal])).extract(
            [rendered_page()], DocumentText(pages=[], used_ocr=False)
        )
    incomplete = SimpleNamespace(status="incomplete", output_parsed=None, output=[])
    with pytest.raises(VisionProviderIncompleteError):
        provider(client([incomplete])).extract(
            [rendered_page()], DocumentText(pages=[], used_ocr=False)
        )
    malformed = SimpleNamespace(status="completed", output_parsed={"bad": True}, output=[])
    with pytest.raises(VisionProviderSchemaError):
        provider(client([malformed])).extract(
            [rendered_page()], DocumentText(pages=[], used_ocr=False)
        )

    monkeypatch.setattr(provider_module, "_is_retryable_openai_error", lambda _: True)
    fake = client([TimeoutError(), TimeoutError()])
    with pytest.raises(VisionProviderTransientError):
        provider(fake, retries=1).extract([rendered_page()], DocumentText(pages=[], used_ocr=False))
    assert len(fake.responses.calls) == 2


def pdf_bytes(page_count: int = 1) -> bytes:
    document = pymupdf.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=400, height=200)
            page.insert_text((20, 30), f"Synthetic page {index}")
        return document.tobytes()
    finally:
        document.close()


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "image/jpeg"])
def test_renderer_supports_inputs_and_bounds_dimensions(content_type: str) -> None:
    body = pdf_bytes()
    if content_type != "application/pdf":
        document = pymupdf.open(stream=body, filetype="pdf")
        try:
            pixmap = document[0].get_pixmap()
            body = pixmap.tobytes("png" if content_type == "image/png" else "jpeg")
        finally:
            document.close()
    pages = PageRenderer(dpi=200, max_dimension=300, max_pages=2).render(body, content_type)
    assert [page.page for page in pages] == [0]
    assert max(pages[0].width, pages[0].height) <= 300
    assert pages[0].mime_type == "image/png"


def test_renderer_classifies_corrupt_and_page_limit_failures() -> None:
    with pytest.raises(DocumentRenderingError):
        PageRenderer().render(b"not-a-document", "application/pdf")
    with pytest.raises(PageLimitExceededError):
        PageRenderer(max_pages=1).render(pdf_bytes(2), "application/pdf")
