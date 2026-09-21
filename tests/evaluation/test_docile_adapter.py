import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from invoiceops.evaluation.adapters.docile import (
    DocileDatasetAdapter,
    DocileEvaluationMode,
    DocileSetupError,
    document_text_from_docile_ocr,
)
from invoiceops.schemas.extraction import TextSource


@dataclass(frozen=True)
class FakeBBox:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class FakeWord:
    text: str
    bbox: FakeBBox


class FakeOcr:
    def get_all_words(self, page: int, snapped: bool = False) -> list[FakeWord]:
        assert snapped is False
        return [
            FakeWord("Invoice", FakeBBox(0.1, 0.1, 0.2, 0.12)),
            FakeWord("Number", FakeBBox(0.21, 0.1, 0.3, 0.12)),
            FakeWord("INV-1", FakeBBox(0.4, 0.1, 0.5, 0.12)),
            FakeWord("Total", FakeBBox(0.1, 0.2, 0.2, 0.22)),
        ]


class FakeAnnotation:
    page_count = 1

    def page_image_size_at_200dpi(self, page: int) -> tuple[int, int]:
        assert page == 0
        return 1200, 1600


class FakeDocument:
    docid = "fake"
    page_count = 1
    ocr = FakeOcr()
    annotation = FakeAnnotation()


def test_precomputed_ocr_preserves_page_coordinates_and_geometric_lines() -> None:
    document = document_text_from_docile_ocr(FakeDocument())  # type: ignore[arg-type]

    assert document.used_ocr is True
    assert document.pages[0].source == TextSource.OCR
    assert {word.page for word in document.pages[0].words} == {0}
    assert document.pages[0].words[0].bbox.model_dump() == {
        "x0": 0.1,
        "y0": 0.1,
        "x1": 0.2,
        "y1": 0.12,
    }
    assert [word.line_number for word in document.pages[0].words] == [0, 0, 0, 1]


def test_missing_dataset_has_clear_setup_error(tmp_path: Path) -> None:
    with pytest.raises(DocileSetupError, match="DOCILE_DATASET_PATH"):
        DocileDatasetAdapter().load_examples(
            tmp_path / "missing",
            tmp_path / "sample.json",
            DocileEvaluationMode.PRECOMPUTED_OCR,
        )


def test_sample_ids_are_validated_then_loaded_as_custom_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset_path = tmp_path / "docile"
    dataset_path.mkdir()
    manifest_path = tmp_path / "sample.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "docile",
                "source_split": "val",
                "seed": 1205,
                "document_ids": ["selected-a", "selected-b"],
            }
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, list[str] | None, bool, bool]] = []

    class StubDocument:
        def __init__(self, docid: str) -> None:
            self.docid = docid

    class StubDataset:
        def __init__(
            self,
            split_name: str,
            dataset_path: Path,
            *,
            load_annotations: bool = True,
            load_ocr: bool = True,
            cache_images: Any,
            docids: list[str] | None = None,
        ) -> None:
            del dataset_path, cache_images
            calls.append((split_name, docids, load_annotations, load_ocr))
            selected = ["selected-a", "selected-b", "other"] if docids is None else docids
            self.documents = [StubDocument(docid) for docid in selected]

        def __iter__(self) -> Any:
            return iter(self.documents)

    monkeypatch.setattr("docile.dataset.Dataset", StubDataset)

    examples = DocileDatasetAdapter().load_examples(
        dataset_path,
        manifest_path,
        DocileEvaluationMode.PRECOMPUTED_OCR,
    )

    assert [example.document_id for example in examples] == ["selected-a", "selected-b"]
    assert calls == [
        ("val", None, False, False),
        ("invoiceops_sample", ["selected-a", "selected-b"], True, True),
    ]
