"""In-process synthetic fixtures, never a model provider or a live-quality benchmark."""

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Literal

from invoiceops.evaluation.hybrid_live import (
    LiveReport,
    Partition,
    _run_hybrid_manifest,
    output_preflight,
)
from invoiceops.evaluation.live_budget import BudgetedVisionProvider, PriceProfile, SpendLedger
from invoiceops.evaluation.live_corpus import CorpusCase, load_corpus
from invoiceops.extraction.hybrid.fusion import HEADER_FIELDS, LINE_FIELDS
from invoiceops.extraction.hybrid.provider import VisionProviderSchemaError
from invoiceops.extraction.hybrid.renderer import PageRenderer
from invoiceops.extraction.hybrid.schemas import (
    CandidateField,
    RenderedPage,
    VisionExtractionResponse,
    VisionInvoiceCandidate,
    VisionUsage,
)
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)

type LocalSourceMode = Literal["native", "synthetic-scan-tokens"]


def _fixture_candidate(case: CorpusCase) -> VisionInvoiceCandidate:
    """Copy labelled printed cells, not arithmetic-derived truth or PO amounts."""
    headers = {}
    for name in HEADER_FIELDS:
        label = next(label for label in case.labels if label.role == name and label.row is None)
        prefix = {"subtotal": "Subtotal: ", "tax": "Tax: ", "total": "Total: "}.get(name, "")
        headers[name] = CandidateField(
            raw_value=label.value, page=label.page, evidence_quote=prefix + label.value
        )
    rows = []
    for row in sorted({label.row for label in case.labels if label.row is not None}):
        labels = [label for label in case.labels if label.row == row]
        quote = " ".join(label.value for label in sorted(labels, key=lambda label: label.bbox.x0))
        cells = {}
        for name in LINE_FIELDS:
            cell_label = next((label for label in labels if label.role == name), None)
            cells[name] = CandidateField(
                raw_value=cell_label.value if cell_label else None,
                page=cell_label.page if cell_label else None,
                evidence_quote=quote if cell_label else None,
            )
        rows.append(cells)
    return VisionInvoiceCandidate.model_validate({**headers, "line_items": rows})


def _page_key(pages: list[RenderedPage]) -> tuple[str, ...]:
    return tuple(hashlib.sha256(page.image_bytes).hexdigest() for page in pages)


class _LocalFixtureProvider(BudgetedVisionProvider):
    """Use the common runner's accounting interface without constructing an SDK/client.

    Intentionally does not call the parent constructor. No credentials, endpoint, HTTP client,
    price verification or external calls exist here. The ledger is simulated and stripped from
    the local report; its generous bound prevents fixture budget abstentions.
    """

    name = "synthetic-local"

    def __init__(self, cases: list[CorpusCase], renderer: PageRenderer) -> None:
        self.fake = True
        self.requested_model = "label-guided-stub-v1"
        self.ledger = SpendLedger(PriceProfile(), Decimal(len(cases) + 1), 4096)
        self._fixtures = {
            _page_key(renderer.render(case.body, case.content_type)): _fixture_candidate(case)
            for case in cases
        }
        if len(self._fixtures) != len(cases):
            raise ValueError("Synthetic fixture image identity is not unique")

    def extract(
        self, pages: list[RenderedPage], document: DocumentText
    ) -> VisionExtractionResponse:
        del document
        candidate = self._fixtures.get(_page_key(pages))
        if candidate is None:
            raise VisionProviderSchemaError("Unknown synthetic fixture")
        self.ledger.reserve()
        usage = VisionUsage(input_tokens=0, output_tokens=0, total_tokens=0)
        self.ledger.settle(usage, verified_response=True)
        return VisionExtractionResponse(
            candidate=candidate, returned_model=self.requested_model, usage=usage, latency_ms=0
        )

    def close(self) -> None:
        pass


class _SyntheticScanTokens(DocumentTextExtractor):
    """Explicit scan fixture: label-derived tokens, not actual OCR. PDFs stay native."""

    def __init__(self, cases: list[CorpusCase]) -> None:
        super().__init__()
        self._scans = {case.body: case for case in cases if case.content_type == "image/png"}

    def extract(self, body: bytes, content_type: str) -> DocumentText:
        if content_type != "image/png":
            return super().extract(body, content_type)
        case = self._scans.get(body)
        if case is None:
            raise ValueError("Unknown synthetic scan fixture")
        words = []
        for index, label in enumerate(case.labels):
            words.append(
                WordToken(
                    text=label.value,
                    page=label.page,
                    bbox=label.bbox,
                    source=TextSource.OCR,
                    block_number=0,
                    line_number=index,
                    word_number=1,
                )
            )
            if label.row is None:
                words.append(
                    WordToken(
                        text=label.role.replace("_", " ") + ":",
                        page=label.page,
                        source=TextSource.OCR,
                        block_number=0,
                        line_number=index,
                        word_number=0,
                        bbox=BoundingBox(
                            x0=max(0, label.bbox.x0 - 0.16),
                            x1=max(0, label.bbox.x0 - 0.005),
                            y0=label.bbox.y0,
                            y1=label.bbox.y1,
                        ),
                    )
                )
        return DocumentText(
            pages=[
                PageText(
                    page=0,
                    width=700,
                    height=700,
                    source=TextSource.OCR,
                    ocr_reason=OcrReason.NO_EMBEDDED_TEXT,
                    words=words,
                )
            ],
            used_ocr=True,
        )


def run_hybrid_local_manifest(
    manifest_path: Path,
    *,
    max_documents: int,
    max_pages: int,
    output_dir: Path,
    repository: Path,
    partition: Partition = "all",
    allow_holdout: bool = False,
    source_mode: LocalSourceMode = "native",
) -> LiveReport:
    """No injectable provider/client: only verified generated assets and in-process fixtures."""
    if source_mode not in ("native", "synthetic-scan-tokens"):
        raise ValueError("Unknown local source mode")
    output_preflight(output_dir, repository)
    cases, _, _ = load_corpus(manifest_path, repository, partition)
    if max_documents <= 0 or max_pages <= 0:
        raise ValueError("Document and page limits must be positive")
    if len(cases) > max_documents or sum(case.pages for case in cases) > max_pages:
        raise ValueError("Corpus exceeds document/page limits")
    if any(case.split == "unseen" for case in cases) and not allow_holdout:
        raise ValueError("Reserved unseen layouts require explicit --allow-holdout")
    renderer = PageRenderer(max_pages=max_pages)
    provider = _LocalFixtureProvider(cases, renderer)
    return _run_hybrid_manifest(
        manifest_path,
        provider,
        renderer,
        max_documents=max_documents,
        max_pages=max_pages,
        output_dir=output_dir,
        repository=repository,
        partition=partition,
        allow_holdout=allow_holdout,
        local_source_mode=source_mode,
        text_extractor=_SyntheticScanTokens(cases)
        if source_mode == "synthetic-scan-tokens"
        else None,
    )
