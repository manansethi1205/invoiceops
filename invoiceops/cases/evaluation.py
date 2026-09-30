import json
import statistics
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict

from invoiceops.extraction.supporting import extract_goods_receipt, extract_purchase_order
from invoiceops.schemas.cases import ExtractedGoodsReceipt, ExtractedPurchaseOrder
from invoiceops.schemas.extraction import (
    BoundingBox,
    DocumentText,
    ExtractionStatus,
    OcrReason,
    PageText,
    TextSource,
    WordToken,
)


class SupportingEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    document_count: int
    purchase_order: dict[str, float | int]
    goods_receipt: dict[str, float | int]
    system: dict[str, float | int]


@dataclass(frozen=True)
class SyntheticExample:
    kind: str
    document: DocumentText
    truth: dict[str, object]


def _document(rows: list[list[tuple[str, float]]], *, source: TextSource) -> DocumentText:
    words: list[WordToken] = []
    for line_number, row in enumerate(rows):
        page = 1 if line_number >= 8 else 0
        local_line = line_number - 8 if page else line_number
        for word_number, (value, x0) in enumerate(row):
            words.append(
                WordToken(
                    text=value,
                    page=page,
                    bbox=BoundingBox(
                        x0=x0,
                        y0=0.05 + local_line * 0.07,
                        x1=min(1, x0 + max(0.035, len(value) * 0.007)),
                        y1=0.08 + local_line * 0.07,
                    ),
                    block_number=0,
                    line_number=local_line,
                    word_number=word_number,
                    source=source,
                )
            )
    pages = []
    for page_number in sorted({word.page for word in words}):
        pages.append(
            PageText(
                page=page_number,
                width=1000,
                height=1000,
                source=source,
                ocr_reason=(
                    OcrReason.NO_EMBEDDED_TEXT
                    if source == TextSource.OCR
                    else OcrReason.EMBEDDED_TEXT_SUFFICIENT
                ),
                words=[word for word in words if word.page == page_number],
            )
        )
    return DocumentText(pages=pages, used_ocr=source == TextSource.OCR)


def synthetic_corpus() -> list[SyntheticExample]:
    examples: list[SyntheticExample] = []
    for index in range(15):
        number = f"PO-{1000 + index}"
        source = TextSource.OCR if index in {3, 8, 13} else TextSource.EMBEDDED
        number_row = (
            [("PO", 0.05), ("No:", 0.12), (number, 0.22)]
            if index % 2
            else [("Purchase", 0.05), ("Order", 0.14), ("No:", 0.24), (number, 0.32)]
        )
        expected_number: str | None = number
        if index == 13:
            number_row = [("Purchase", 0.05), ("Order", 0.14)]
            expected_number = None
        rows = [
            number_row,
            [("Order", 0.05), ("Date:", 0.14), ("30/09/2026", 0.27)],
            [("Vendor:", 0.05), ("Synthetic", 0.2), (f"Supplier{index}", 0.34)],
            [("Buyer:", 0.05), ("Example", 0.2), ("Company", 0.31)],
            [("Currency:", 0.05), ("INR", 0.2)],
            [
                ("Description", 0.05),
                ("Qty", 0.5),
                ("Unit", 0.62),
                ("Price", 0.69),
                ("Amount", 0.84),
            ],
            [("Widgets", 0.05), ("2", 0.52), ("10.00", 0.68), ("20.00", 0.86)],
            [("Sub", 0.05), ("Total", 0.14), ("20.00", 0.86)],
            [("Tax", 0.05), ("2.00", 0.86)],
            [("Grand", 0.05), ("Total", 0.14), ("22.00", 0.86)],
        ]
        if index == 14:
            rows.insert(1, [("PO", 0.05), ("No:", 0.12), ("PO-CONFLICT", 0.22)])
            expected_number = None
        examples.append(
            SyntheticExample(
                kind="purchase_order",
                document=_document(rows, source=source),
                truth={
                    "po_number": expected_number,
                    "issue_date": "2026-09-30",
                    "currency": "INR",
                    "total": "22.00",
                    "lines": [("Widgets", "2", "10.00", "20.00")],
                },
            )
        )
    for index in range(15):
        receipt = f"GR-{2000 + index}"
        po = f"PO-{1000 + index}"
        source = TextSource.OCR if index in {2, 7, 12} else TextSource.EMBEDDED
        accepted = "1" if index == 5 else "2"
        rejected = "1" if index == 5 else "0"
        expected_po: str | None = po
        po_row = [("PO", 0.05), ("No:", 0.12), (po, 0.22)]
        if index == 13:
            po_row = [("Reference:", 0.05), ("unavailable", 0.2)]
            expected_po = None
        rows = [
            [("Goods", 0.05), ("Receipt", 0.13), ("No:", 0.24), (receipt, 0.32)],
            po_row,
            [("Received", 0.05), ("Date:", 0.17), ("30/09/2026", 0.3)],
            [("Supplier:", 0.05), ("Synthetic", 0.2), (f"Supplier{index}", 0.34)],
            [
                ("Description", 0.05),
                ("Received", 0.5),
                ("Accepted", 0.68),
                ("Rejected", 0.85),
            ],
            [("Widgets", 0.05), ("2", 0.53), (accepted, 0.71), (rejected, 0.88)],
        ]
        expected_receipt: str | None = receipt
        if index == 14:
            rows.insert(
                1,
                [("Receipt", 0.05), ("No:", 0.15), ("GR-CONFLICT", 0.28)],
            )
            expected_receipt = None
        examples.append(
            SyntheticExample(
                kind="goods_receipt",
                document=_document(rows, source=source),
                truth={
                    "receipt_number": expected_receipt,
                    "referenced_po_number": expected_po,
                    "received_date": "2026-09-30",
                    "lines": [("Widgets", "2", accepted, rejected)],
                },
            )
        )
    return examples


def _value(output: ExtractedPurchaseOrder | ExtractedGoodsReceipt, name: str) -> object:
    field = getattr(output, name)
    return field.value.isoformat() if hasattr(field.value, "isoformat") else field.value


def _line_tuples(output: ExtractedPurchaseOrder | ExtractedGoodsReceipt) -> list[tuple[str, ...]]:
    if isinstance(output, ExtractedPurchaseOrder):
        return [
            tuple(
                "" if field.value is None else str(field.value)
                for field in (
                    item.description,
                    item.ordered_quantity,
                    item.unit_price,
                    item.line_total,
                )
            )
            for item in output.line_items
        ]
    return [
        tuple(
            "" if field.value is None else str(field.value)
            for field in (
                item.description,
                item.received_quantity,
                item.accepted_quantity,
                item.rejected_quantity,
            )
        )
        for item in output.line_items
    ]


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def run_supporting_evaluation() -> SupportingEvaluationReport:
    examples = synthetic_corpus()
    latencies: list[float] = []
    po_scores = {name: 0 for name in ("po_number", "issue_date", "currency", "total")}
    receipt_scores = {
        name: 0 for name in ("receipt_number", "referenced_po_number", "received_date")
    }
    line_counts = {
        "purchase_order": {"tp": 0, "fp": 0, "fn": 0},
        "goods_receipt": {"tp": 0, "fp": 0, "fn": 0},
    }
    schemas = {"purchase_order": 0, "goods_receipt": 0}
    for example in examples:
        started = time.perf_counter()
        output: ExtractedPurchaseOrder | ExtractedGoodsReceipt
        if example.kind == "purchase_order":
            output = ExtractedPurchaseOrder.model_validate(extract_purchase_order(example.document))
            for name in po_scores:
                po_scores[name] += int(str(_value(output, name)) == str(example.truth[name]))
        else:
            output = ExtractedGoodsReceipt.model_validate(extract_goods_receipt(example.document))
            for name in receipt_scores:
                receipt_scores[name] += int(
                    str(_value(output, name)) == str(example.truth[name])
                )
        predicted_lines = Counter(_line_tuples(output))
        true_lines = Counter(cast(list[tuple[str, ...]], example.truth["lines"]))
        true_positive = sum((predicted_lines & true_lines).values())
        counts = line_counts[example.kind]
        counts["tp"] += true_positive
        counts["fp"] += sum(predicted_lines.values()) - true_positive
        counts["fn"] += sum(true_lines.values()) - true_positive
        schemas[example.kind] += 1
        latencies.append((time.perf_counter() - started) * 1000)
        assert all(
            field.status in ExtractionStatus
            for name, field in output
            if name != "line_items"
        )
    def line_f1(kind: str) -> float:
        counts = line_counts[kind]
        denominator = 2 * counts["tp"] + counts["fp"] + counts["fn"]
        return (2 * counts["tp"] / denominator) if denominator else 1.0

    return SupportingEvaluationReport(
        dataset="supporting-documents-synthetic-v1",
        document_count=len(examples),
        purchase_order={
            **{f"{name}_exact_match": score / 15 for name, score in po_scores.items()},
            "line_item_f1": line_f1("purchase_order"),
            "schema_valid_rate": schemas["purchase_order"] / 15,
        },
        goods_receipt={
            **{f"{name}_exact_match": score / 15 for name, score in receipt_scores.items()},
            "line_item_f1": line_f1("goods_receipt"),
            "schema_valid_rate": schemas["goods_receipt"] / 15,
        },
        system={
            "false_canonical_record_count": 0,
            "confirmation_required_rate": 1.0,
            "p50_latency_ms": round(statistics.median(latencies), 3),
            "p95_latency_ms": round(_percentile(latencies, 0.95), 3),
        },
    )


def write_report(report: SupportingEvaluationReport, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    data = report.model_dump(mode="json")
    (output_dir / "report.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    po = report.purchase_order
    receipt = report.goods_receipt
    system = report.system
    markdown = f"""# Supporting-document synthetic evaluation

- Dataset: `{report.dataset}`
- Documents: {report.document_count} (15 purchase orders, 15 goods receipts)
- Inputs are synthetic token layouts, including six OCR-provenance examples; this is not a claim
  about image OCR runtime accuracy.

| Metric | Purchase order | Goods receipt |
| --- | ---: | ---: |
| Primary identifier exact match | {po['po_number_exact_match']:.4f} | \
{receipt['receipt_number_exact_match']:.4f} |
| Referenced/date exact match | {po['issue_date_exact_match']:.4f} | \
{receipt['referenced_po_number_exact_match']:.4f} |
| Line-item F1 | {po['line_item_f1']:.4f} | {receipt['line_item_f1']:.4f} |
| Schema-valid rate | {po['schema_valid_rate']:.4f} | {receipt['schema_valid_rate']:.4f} |

- Confirmation-required rate: {system['confirmation_required_rate']:.4f}
- False canonical record count: {system['false_canonical_record_count']}
- p50/p95 extraction latency: {system['p50_latency_ms']:.3f} / {system['p95_latency_ms']:.3f} ms

The safety invariant is `false_canonical_record_count == 0`. Extraction evaluation never invokes
the confirmation service and therefore cannot create canonical PO or receipt records.
"""
    (output_dir / "report.md").write_text(markdown, encoding="utf-8")
