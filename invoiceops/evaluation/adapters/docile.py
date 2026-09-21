import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.extraction.table_layout import reconstruct_visual_rows
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    Invoice,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


class DocileEvaluationMode(StrEnum):
    END_TO_END = "end_to_end"
    PRECOMPUTED_OCR = "precomputed_ocr"


class DocileSetupError(RuntimeError):
    pass


class DocileSampleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset: str = "docile"
    source_split: str = "val"
    seed: int = 1205
    document_ids: list[str] = Field(min_length=1)


class _BBoxLike(Protocol):
    left: float
    top: float
    right: float
    bottom: float


class _WordLike(Protocol):
    text: str | None
    bbox: _BBoxLike


class _OcrLike(Protocol):
    def get_all_words(self, page: int, snapped: bool = False) -> Sequence[_WordLike]: ...


class _AnnotationLike(Protocol):
    page_count: int

    def page_image_size_at_200dpi(self, page: int) -> Sequence[float]: ...


class _DataPathsLike(Protocol):
    def pdf_path(self, docid: str) -> Any: ...


class DocileDocumentLike(Protocol):
    docid: str
    page_count: int
    ocr: _OcrLike
    annotation: _AnnotationLike
    data_paths: _DataPathsLike


@dataclass(frozen=True)
class DocileExample:
    document_id: str
    document: DocileDocumentLike
    mode: DocileEvaluationMode


def _page_size(document: DocileDocumentLike, page: int) -> tuple[float, float]:
    try:
        size = document.annotation.page_image_size_at_200dpi(page)
        width, height = float(size[0]), float(size[1])
    except (AttributeError, IndexError, TypeError, ValueError):
        return 1.0, 1.0
    return (width, height) if width > 0 and height > 0 else (1.0, 1.0)


def document_text_from_docile_ocr(document: DocileDocumentLike) -> DocumentText:
    pages: list[PageText] = []
    for page_number in range(document.page_count):
        provisional: list[WordToken] = []
        for word_number, raw_word in enumerate(
            document.ocr.get_all_words(page_number, snapped=False)
        ):
            text = raw_word.text or ""
            if not text.strip():
                continue
            bbox = raw_word.bbox
            provisional.append(
                WordToken(
                    text=text,
                    page=page_number,
                    bbox=BoundingBox(
                        x0=float(bbox.left),
                        y0=float(bbox.top),
                        x1=float(bbox.right),
                        y1=float(bbox.bottom),
                    ),
                    block_number=0,
                    line_number=0,
                    word_number=word_number,
                    source=TextSource.OCR,
                )
            )
        width, height = _page_size(document, page_number)
        provisional_page = PageText(
            page=page_number,
            width=width,
            height=height,
            source=TextSource.OCR,
            ocr_reason=OcrReason.NO_EMBEDDED_TEXT,
            words=provisional,
        )
        provisional_document = DocumentText(pages=[provisional_page], used_ocr=True)
        line_by_word: dict[int, tuple[int, int]] = {}
        for line_number, row in enumerate(reconstruct_visual_rows(provisional_document)):
            for position, word in enumerate(row.words):
                line_by_word[word.word_number] = (line_number, position)
        normalized_words = [
            word.model_copy(
                update={
                    "line_number": line_by_word[word.word_number][0],
                    "word_number": line_by_word[word.word_number][1],
                }
            )
            for word in provisional
        ]
        pages.append(provisional_page.model_copy(update={"words": normalized_words}))
    return DocumentText(pages=pages, used_ocr=True)


class DocileDatasetAdapter:
    def __init__(
        self,
        *,
        text_extractor: DocumentTextExtractor | None = None,
        invoice_extractor: DeterministicInvoiceExtractor | None = None,
    ) -> None:
        self.text_extractor = text_extractor or DocumentTextExtractor()
        self.invoice_extractor = invoice_extractor or DeterministicInvoiceExtractor()

    def load_examples(
        self,
        dataset_path: Path,
        sample_manifest: Path,
        mode: DocileEvaluationMode,
    ) -> list[DocileExample]:
        if not dataset_path.exists():
            raise DocileSetupError(
                "DocILE dataset was not found. Set DOCILE_DATASET_PATH to the extracted "
                "annotated-trainval dataset."
            )
        manifest = load_sample_manifest(sample_manifest)
        if manifest.dataset != "docile" or manifest.source_split != "val":
            raise DocileSetupError("DocILE sample manifest must target the val split")
        try:
            from docile.dataset import CachingConfig, Dataset
        except ImportError as exc:
            raise DocileSetupError(
                "docile-benchmark is not installed; install the evaluation dependency group"
            ) from exc
        validation_dataset = Dataset(
            "val",
            dataset_path,
            load_annotations=False,
            load_ocr=False,
            cache_images=CachingConfig.OFF,
        )
        available_ids = {str(document.docid) for document in validation_dataset}
        missing = set(manifest.document_ids) - available_ids
        if missing:
            raise DocileSetupError(
                f"DocILE sample contains {len(missing)} unknown document IDs"
            )

        # docile-benchmark requires docids passed with an indexed split (such as
        # ``val``) to exactly equal that split's complete index. Use an unindexed
        # custom split for the validated subset instead.
        dataset = Dataset(
            "invoiceops_sample",
            dataset_path,
            cache_images=CachingConfig.OFF,
            docids=manifest.document_ids,
        )
        documents = list(dataset)
        loaded_ids = {str(document.docid) for document in documents}
        missing = set(manifest.document_ids) - loaded_ids
        if missing:
            raise DocileSetupError(f"DocILE sample contains {len(missing)} unknown document IDs")
        return [
            DocileExample(str(document.docid), cast(DocileDocumentLike, document), mode)
            for document in documents
        ]

    def extract(self, example: DocileExample) -> Invoice:
        if example.mode == DocileEvaluationMode.PRECOMPUTED_OCR:
            document_text = document_text_from_docile_ocr(example.document)
        else:
            pdf_path = example.document.data_paths.pdf_path(example.document_id)
            document_text = self.text_extractor.extract(pdf_path.read_bytes(), "application/pdf")
        return self.invoice_extractor.extract(document_text)


def load_sample_manifest(path: Path) -> DocileSampleManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DocileSetupError("DocILE sample manifest could not be loaded") from exc
    return DocileSampleManifest.model_validate(payload)
