import json
import socket
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from invoiceops.evaluation.failure_attribution import (
    AttributionReport,
    Probe,
    SourceCheck,
    TracedExtractor,
    analyze,
    check_source,
    classify,
    combine,
    run_attribution,
)
from invoiceops.evaluation.human_annotations import HumanField, HumanInvoiceAnnotation
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.schemas.extraction import (
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    InvoiceLine,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)
from tests.evaluation.test_real_input import annotation, dataset
from tests.synthetic_documents import generated_invoice_pdf


def word(text: str, x: float = 0.1, y: float = 0.2) -> WordToken:
    return WordToken(
        text=text,
        page=0,
        bbox=dict(x0=x, x1=x + 0.05, y0=y, y1=y + 0.02),
        block_number=0,
        line_number=int(y * 100),
        word_number=int(x * 100),
        source=TextSource.EMBEDDED,
    )


def doc(words: list[WordToken]) -> DocumentText:
    return DocumentText(
        used_ocr=False,
        pages=[
            PageText(
                page=0,
                width=600,
                height=800,
                source=TextSource.EMBEDDED,
                ocr_reason=OcrReason.EMBEDDED_TEXT_SUFFICIENT,
                words=words,
            )
        ],
    )


def label(value: Any, words: list[WordToken]) -> HumanField[Any]:
    return HumanField[Any](
        status="present", value=value, evidence=[dict(page=w.page, bbox=w.bbox) for w in words]
    )


def prediction(value: Any, words: list[WordToken]) -> ExtractedField[Any]:
    return ExtractedField[Any](
        value=value,
        status=ExtractionStatus.EXTRACTED,
        evidence=[
            EvidenceSpan(page=w.page, bbox=w.bbox, text=w.text, source=w.source) for w in words
        ],
    )


@pytest.mark.parametrize(
    ("region", "category"), [(False, "region_not_detected"), (True, "candidate_not_emitted")]
)
def test_detected_but_unparsed(region: bool, category: str) -> None:
    w = word("100")
    assert (
        classify(
            label(Decimal(100), [w]),
            "total",
            None,
            SourceCheck("found", [w]),
            region=region,
            candidates=0,
        )
        == category
    )


def test_missing_tokens_and_ambiguous_boxes() -> None:
    w = word("100")
    field = label(Decimal(100), [w])
    assert check_source(field, "total", doc([])).state == "tokens_not_observed"
    assert (
        check_source(field, "total", doc([word("100", y=0.6)])).state
        == "annotation_or_tokens_unresolved"
    )
    second = word("100", x=0.3)
    assert (
        check_source(label(Decimal(100), [w, second]), "total", doc([w, second])).state
        == "annotation_or_tokens_unresolved"
    )


@pytest.mark.parametrize(
    ("role", "row", "scorer", "expected"),
    [
        (True, False, False, "wrong_role"),
        (False, True, False, "wrong_row"),
        (False, False, True, "scorer_only"),
        (False, False, False, "correct"),
    ],
)
def test_role_row_and_scorer_categories(role: bool, row: bool, scorer: bool, expected: str) -> None:
    w = word("100")
    assert (
        classify(
            label(Decimal(100), [w]),
            "total",
            prediction(Decimal(100), [w]),
            SourceCheck("found", [w]),
            region=True,
            candidates=1,
            other_role=role,
            wrong_row=row,
            scorer_rejected=scorer,
        )
        == expected
    )


def test_total_subtotal_confusion_requires_location() -> None:
    net, gross = word("100"), word("120", y=0.4)
    truth = HumanInvoiceAnnotation(
        annotation_version="human-invoice-v1",
        provenance="human",
        subtotal=label(Decimal(100), [net]),
        total=label(Decimal(120), [gross]),
    )
    document = doc([net, gross])
    invoice = DeterministicInvoiceExtractor().extract(document)
    invoice.total = prediction(Decimal(100), [net])
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.total_equals_subtotal == part.total_equals_subtotal_location_supported == 1
    assert part.headers["total"].categories == {"wrong_role": 1}
    invoice.total = prediction(Decimal(100), [gross])
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.total_equals_subtotal == 1
    assert part.total_equals_subtotal_location_supported == 0
    assert part.headers["total"].categories == {"wrong_value": 1}


def test_reordered_rows_can_be_scorer_only_without_index_association() -> None:
    rows, predictions, words = [], [], []
    for index, name in enumerate(("Widget", "Cable")):
        w = word(name, y=0.2 + index * 0.3)
        amount = word(str(100 + index), x=0.5, y=w.bbox.y0)
        words += [w, amount]
        rows.append(
            dict(
                description=label(name, [w]).model_dump(),
                quantity=dict(status="absent"),
                unit_price=dict(status="absent"),
                line_total=label(Decimal(100 + index), [amount]).model_dump(),
            )
        )
        missing = ExtractedField[Any](value=None, status=ExtractionStatus.MISSING, evidence=[])
        predictions.append(
            InvoiceLine(
                description=prediction(name, [w]),
                quantity=missing,
                unit_price=missing,
                line_total=prediction(Decimal(100 + index), [amount]),
            )
        )
    truth = HumanInvoiceAnnotation.model_validate(
        dict(
            annotation_version="human-invoice-v1",
            provenance="human",
            line_items=dict(status="present", rows=rows),
        )
    )
    document = doc(words)
    invoice = DeterministicInvoiceExtractor().extract(document)
    invoice.line_items = list(reversed(predictions))
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.associated_predicted_rows == 2
    assert part.rows == {"exact": 1, "scorer_only": 1}
    assert part.cells["description"].categories == {"correct": 1, "scorer_only": 1}
    combine([part, part])


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("work/\n", encoding="utf-8")
    return tmp_path


def test_private_report_privacy_reconciliation_and_overwrite(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Network forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    manifest = dataset(repository, labels=[annotation(generated_invoice_pdf())])
    output = repository / "evals/reports/real-input/attribution"
    private = repository / "work/real-invoice-private/diagnostics/new"
    report = run_attribution(manifest, output, private, repository=repository)
    assert report.attempted_documents == 1
    part = report.slices["all"]
    assert part.rows_denominator == 2
    assert sum(part.rows.values()) == 2
    assert sum(t.denominator for t in part.cells.values()) == 8
    content = (output / "report.json").read_text(encoding="utf-8")
    assert "SYN-12345" not in content
    assert "private-id" not in content and str(repository) not in content
    assert not {"document_id", "annotation", "candidates", "result"} & json.loads(content).keys()
    AttributionReport.model_validate_json(content)
    assert (private / "cases.jsonl").exists()
    frozen = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        run_attribution(manifest, output, private, repository=repository)
    assert (output / "report.json").read_bytes() == frozen
    with pytest.raises(ValueError):
        run_attribution(
            manifest,
            repository / "evals/reports/real-input/another",
            repository / "public-private",
            repository=repository,
        )


def test_instrumentation_preserves_extraction() -> None:
    words = [word("Grand", x=0.1), word("total", x=0.2), word("100", x=0.4)]
    document = doc(words)
    normal = DeterministicInvoiceExtractor().extract(document)
    traced = TracedExtractor()
    assert traced.extract(document) == normal
    assert traced.probe.candidates["total"]


def test_wrong_column_roles_and_mixed_rows_abstain() -> None:
    description, qty, amount = word("Widget"), word("2", x=0.3), word("100", x=0.5)
    row = dict(
        description=label("Widget", [description]).model_dump(),
        quantity=label(Decimal(2), [qty]).model_dump(),
        unit_price=dict(status="absent"),
        line_total=label(Decimal(100), [amount]).model_dump(),
    )
    truth = HumanInvoiceAnnotation.model_validate(
        dict(
            annotation_version="human-invoice-v1",
            provenance="human",
            line_items=dict(status="present", rows=[row]),
        )
    )
    document = doc([description, qty, amount])
    invoice = DeterministicInvoiceExtractor().extract(document)
    missing = ExtractedField[Any](value=None, status=ExtractionStatus.MISSING, evidence=[])
    invoice.line_items = [
        InvoiceLine(
            description=prediction("Widget", [description]),
            quantity=prediction(Decimal(100), [amount]),
            unit_price=missing,
            line_total=prediction(Decimal(2), [qty]),
        )
    ]
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.predicted_rows_with_wrong_column_semantics == 1
    assert part.cells["quantity"].categories == {"wrong_role": 1}
    assert part.cells["line_total"].categories == {"wrong_role": 1}
    other = word("Cable", y=0.6)
    other_amount = word("200", x=0.5, y=0.6)
    row2 = dict(
        description=label("Cable", [other]).model_dump(),
        quantity=dict(status="absent"),
        unit_price=dict(status="absent"),
        line_total=label(Decimal(200), [other_amount]).model_dump(),
    )
    truth = HumanInvoiceAnnotation.model_validate(
        dict(
            annotation_version="human-invoice-v1",
            provenance="human",
            line_items=dict(status="present", rows=[row, row2]),
        )
    )
    document = doc([description, qty, amount, other, other_amount])
    invoice.line_items[0].line_total = prediction(Decimal(200), [other_amount])
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.associated_predicted_rows == 0
    assert part.ambiguous_predicted_rows == 1
    assert part.rows == {"ambiguous_association": 2}


def test_missing_row_is_not_correct_cell_absence() -> None:
    description, amount = word("Widget"), word("100", x=0.5)
    truth = HumanInvoiceAnnotation.model_validate(
        dict(
            annotation_version="human-invoice-v1",
            provenance="human",
            line_items=dict(
                status="present",
                rows=[
                    dict(
                        description=label("Widget", [description]).model_dump(),
                        quantity=dict(status="absent"),
                        unit_price=dict(status="absent"),
                        line_total=label(Decimal(100), [amount]).model_dump(),
                    )
                ],
            ),
        )
    )
    document = doc([description, amount])
    invoice = DeterministicInvoiceExtractor().extract(document)
    assert not invoice.line_items
    _, part, _ = analyze(truth, document, invoice, Probe())
    assert part.rows == {"no_detected_header": 1}
    assert part.cells["quantity"].categories == {"absence_unscorable": 1}


def test_attribution_import_graph_is_provider_free() -> None:
    code = """
import importlib.abc, socket, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'openai', 'httpx', 'httpcore'}:
            raise AssertionError('External SDK forbidden')
def refused(*args, **kwargs):
    raise AssertionError('Network forbidden')
sys.meta_path.insert(0, Guard())
socket.socket.connect = refused
socket.create_connection = refused
import scripts.run_private_failure_attribution
assert not any(k.startswith('invoiceops.extraction.hybrid') for k in sys.modules)
"""
    subprocess.run([sys.executable, "-c", code], capture_output=True, check=True)
