from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from invoiceops.schemas.extraction import BoundingBox, DocumentText, WordToken


class TextLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=0)
    block_number: int = Field(ge=0)
    line_number: int = Field(ge=0)
    text: str
    bbox: BoundingBox
    words: list[WordToken] = Field(min_length=1)


def union_bbox(words: list[WordToken]) -> BoundingBox:
    if not words:
        raise ValueError("cannot calculate a line bounding box without words")
    return BoundingBox(
        x0=min(word.bbox.x0 for word in words),
        y0=min(word.bbox.y0 for word in words),
        x1=max(word.bbox.x1 for word in words),
        y1=max(word.bbox.y1 for word in words),
    )


def reconstruct_lines(document: DocumentText) -> list[TextLine]:
    grouped: dict[tuple[int, int, int], list[WordToken]] = defaultdict(list)
    for document_page in document.pages:
        for word in document_page.words:
            grouped[(word.page, word.block_number, word.line_number)].append(word)

    lines: list[TextLine] = []
    for (page_number, block_number, line_number), words in grouped.items():
        ordered_words = sorted(words, key=lambda word: (word.word_number, word.bbox.x0))
        lines.append(
            TextLine(
                page=page_number,
                block_number=block_number,
                line_number=line_number,
                text=" ".join(word.text for word in ordered_words),
                bbox=union_bbox(ordered_words),
                words=ordered_words,
            )
        )
    return sorted(lines, key=lambda line: (line.page, line.bbox.y0, line.bbox.x0))
