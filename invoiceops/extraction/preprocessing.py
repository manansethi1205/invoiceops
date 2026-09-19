from collections.abc import Callable, Sequence
from typing import cast

import pymupdf

from invoiceops.extraction.errors import (
    EncryptedDocumentError,
    OcrUnavailableError,
    UnreadableDocumentError,
    UnsupportedDocumentTypeError,
)
from invoiceops.extraction.normalization import normalize_bbox
from invoiceops.schemas.extraction import (
    DocumentText,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)

type RawWord = tuple[float, float, float, float, str, int, int, int]
type OcrWordExtractor = Callable[[pymupdf.Page], Sequence[object]]
SUPPORTED_CONTENT_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpeg",
    "image/png": "png",
}


class DocumentTextExtractor:
    def __init__(
        self,
        *,
        minimum_meaningful_words: int = 8,
        minimum_non_whitespace_characters: int = 40,
        ocr_word_extractor: OcrWordExtractor | None = None,
    ) -> None:
        if minimum_meaningful_words < 0 or minimum_non_whitespace_characters < 0:
            raise ValueError("text sufficiency thresholds must be non-negative")
        self.minimum_meaningful_words = minimum_meaningful_words
        self.minimum_non_whitespace_characters = minimum_non_whitespace_characters
        self.ocr_word_extractor = ocr_word_extractor or self._extract_ocr_words

    def extract(self, body: bytes, content_type: str) -> DocumentText:
        filetype = SUPPORTED_CONTENT_TYPES.get(content_type)
        if filetype is None:
            raise UnsupportedDocumentTypeError(f"unsupported content type: {content_type}")
        try:
            document = pymupdf.open(stream=body, filetype=filetype)
        except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
            raise UnreadableDocumentError("document bytes could not be decoded") from exc

        try:
            if document.needs_pass:
                raise EncryptedDocumentError("password-protected documents are not supported")
            pages = [
                self._extract_page(page_number, document.load_page(page_number))
                for page_number in range(document.page_count)
            ]
        finally:
            document.close()
        return DocumentText(
            pages=pages,
            used_ocr=any(page.source == TextSource.OCR for page in pages),
        )

    def _extract_page(self, page_number: int, page: pymupdf.Page) -> PageText:
        try:
            embedded_words = self._coerce_words(page.get_text("words", sort=True))
        except RuntimeError as exc:
            raise UnreadableDocumentError(
                f"embedded text could not be read from page {page_number}"
            ) from exc
        reason = self._ocr_reason(embedded_words)
        source = TextSource.EMBEDDED
        raw_words = embedded_words
        if reason != OcrReason.EMBEDDED_TEXT_SUFFICIENT:
            raw_words = self._coerce_words(self.ocr_word_extractor(page))
            source = TextSource.OCR

        rect = page.rect
        words = [
            WordToken(
                text=word[4],
                page=page_number,
                bbox=normalize_bbox(
                    word[0],
                    word[1],
                    word[2],
                    word[3],
                    page_x0=rect.x0,
                    page_y0=rect.y0,
                    page_width=rect.width,
                    page_height=rect.height,
                ),
                block_number=word[5],
                line_number=word[6],
                word_number=word[7],
                source=source,
            )
            for word in raw_words
            if word[4].strip()
        ]
        return PageText(
            page=page_number,
            width=rect.width,
            height=rect.height,
            source=source,
            ocr_reason=reason,
            words=words,
        )

    def _ocr_reason(self, words: Sequence[RawWord]) -> OcrReason:
        extracted_text = [word[4] for word in words if word[4].strip()]
        meaningful = [text.strip() for text in extracted_text if self._is_meaningful(text)]
        if not meaningful:
            return OcrReason.NO_EMBEDDED_TEXT
        if len(meaningful) < self.minimum_meaningful_words:
            return OcrReason.TOO_FEW_EMBEDDED_WORDS
        character_count = sum(len("".join(text.split())) for text in extracted_text)
        if character_count < self.minimum_non_whitespace_characters:
            return OcrReason.EMBEDDED_TEXT_TOO_SHORT
        return OcrReason.EMBEDDED_TEXT_SUFFICIENT

    @staticmethod
    def _is_meaningful(text: str) -> bool:
        stripped = text.strip()
        return bool(stripped) and any(character.isalnum() for character in stripped)

    @staticmethod
    def _coerce_words(values: Sequence[object]) -> list[RawWord]:
        words: list[RawWord] = []
        for value in values:
            if not isinstance(value, (tuple, list)) or len(value) < 8:
                raise UnreadableDocumentError("text extraction returned malformed word data")
            try:
                words.append(
                    (
                        float(value[0]),
                        float(value[1]),
                        float(value[2]),
                        float(value[3]),
                        str(value[4]),
                        int(value[5]),
                        int(value[6]),
                        int(value[7]),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise UnreadableDocumentError(
                    "text extraction returned malformed word data"
                ) from exc
        return words

    @staticmethod
    def _extract_ocr_words(page: pymupdf.Page) -> Sequence[object]:
        try:
            text_page = page.get_textpage_ocr(language="eng", dpi=200, full=True)
            return cast(Sequence[object], page.get_text("words", textpage=text_page, sort=True))
        except RuntimeError as exc:
            raise OcrUnavailableError("OCR failed or the Tesseract runtime is unavailable") from exc
