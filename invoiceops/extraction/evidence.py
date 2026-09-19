from collections import defaultdict

from invoiceops.extraction.layout import union_bbox
from invoiceops.schemas.extraction import EvidenceSpan, TextSource, WordToken


def evidence_from_words(words: list[WordToken]) -> list[EvidenceSpan]:
    grouped: dict[tuple[int, TextSource], list[WordToken]] = defaultdict(list)
    for word in words:
        grouped[(word.page, word.source)].append(word)

    evidence: list[EvidenceSpan] = []
    for (page, source), source_words in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1].value)
    ):
        ordered = sorted(
            source_words,
            key=lambda word: (
                (word.bbox.y0 + word.bbox.y1) / 2,
                word.bbox.x0,
                word.word_number,
            ),
        )
        evidence.append(
            EvidenceSpan(
                page=page,
                bbox=union_bbox(ordered),
                text=" ".join(word.text for word in ordered),
                source=source,
            )
        )
    return evidence
