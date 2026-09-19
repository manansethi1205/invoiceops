from datetime import date
from decimal import Decimal
from pathlib import Path

from invoiceops.evaluation.metrics import calculate_metrics, calculate_tagged_slices
from invoiceops.evaluation.schemas import (
    EvaluationExample,
    EvaluationPrediction,
    EvaluationResult,
    GroundTruthInvoice,
    GroundTruthLineItem,
)
from invoiceops.schemas.extraction import (
    BoundingBox,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    Invoice,
    InvoiceLine,
    TextSource,
)


def _field(value: object | None) -> ExtractedField[object]:
    return ExtractedField[object](
        value=value,
        status=ExtractionStatus.MISSING if value is None else ExtractionStatus.EXTRACTED,
        evidence=[]
        if value is None
        else [
            EvidenceSpan(
                page=0,
                bbox=BoundingBox(x0=0, y0=0, x1=0.1, y1=0.1),
                text="synthetic",
                source=TextSource.EMBEDDED,
            )
        ],
        rule_id=None if value is None else "test.synthetic.v1",
    )


def _invoice(*, number: str | None, line_total: str = "10") -> Invoice:
    return Invoice(
        invoice_number=_field(number),
        invoice_date=_field(date(2026, 9, 19)),
        currency=_field("INR"),
        subtotal=_field(Decimal("10")),
        tax=_field(Decimal("0")),
        total=_field(Decimal("10")),
        line_items=[
            InvoiceLine(
                description=_field("Filter"),
                quantity=_field(Decimal("1")),
                unit_price=_field(Decimal("10")),
                line_total=_field(Decimal(line_total)),
            )
        ],
    )


def _result(document_id: str, invoice: Invoice, *, layout: str) -> EvaluationResult:
    return EvaluationResult(
        example=EvaluationExample(
            document_id=document_id,
            split="development",
            document_path=Path("doc.pdf"),
            content_type="application/pdf",
            ground_truth_path=Path("truth.json"),
            tags={"layout": layout},
        ),
        ground_truth=GroundTruthInvoice(
            invoice_number="INV-1",
            invoice_date="2026-09-19",
            currency="INR",
            subtotal="10",
            tax="0",
            total="10",
            line_items=[
                GroundTruthLineItem(
                    description="Filter", quantity="1", unit_price="10", line_total="10"
                )
            ],
        ),
        prediction=EvaluationPrediction(
            document_id=document_id,
            invoice=invoice,
            schema_valid=True,
            used_ocr=False,
            page_count=1,
            latency_ms=5,
        ),
        document_sha256="0" * 64,
        ground_truth_sha256="1" * 64,
    )


def test_metric_denominators_distinguish_coverage_and_accuracy() -> None:
    metrics = calculate_metrics(
        [
            _result("one", _invoice(number="INV-1"), layout="a"),
            _result("two", _invoice(number=None), layout="b"),
        ]
    )

    invoice_number = metrics["headers"]["invoice_number"]
    assert invoice_number == {
        "labeled": 2,
        "extracted": 1,
        "correct": 1,
        "coverage": 0.5,
        "conditional_exact_accuracy": 1.0,
        "overall_exact_accuracy": 0.5,
    }
    assert metrics["line_items"]["exact_f1"] == 1.0


def test_tagged_slices_recompute_metrics() -> None:
    slices = calculate_tagged_slices(
        [
            _result("one", _invoice(number="INV-1"), layout="a"),
            _result("two", _invoice(number=None), layout="b"),
        ]
    )
    assert slices["layout=a"]["documents"]["attempted"] == 1
    assert slices["layout=b"]["documents"]["attempted"] == 1
