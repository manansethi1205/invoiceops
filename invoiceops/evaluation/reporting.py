import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoiceops.evaluation.matching import LINE_FIELDS, align_line_items
from invoiceops.evaluation.metrics import HEADER_FIELDS
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.schemas import EvaluationResult
from invoiceops.schemas.extraction import ExtractedField, ExtractionStatus


def _field_payload(field: ExtractedField[Any]) -> dict[str, object]:
    status = field.status
    value = field.value
    rule_id = field.rule_id
    return {
        "value": value.isoformat() if isinstance(value, date) else value,
        "status": str(status),
        "rule_id": rule_id,
    }


def _prediction_payload(result: EvaluationResult) -> dict[str, object]:
    prediction = result.prediction
    invoice = prediction.invoice
    invoice_payload: dict[str, object] | None = None
    if invoice is not None:
        invoice_payload = {
            field_name: _field_payload(getattr(invoice, field_name))
            for field_name in HEADER_FIELDS
        }
        invoice_payload["line_items"] = [
            {
                field_name: _field_payload(getattr(line, field_name))
                for field_name in LINE_FIELDS
            }
            for line in invoice.line_items
        ]
    return {
        "document_id": prediction.document_id,
        "invoice": invoice_payload,
        "schema_valid": prediction.schema_valid,
        "used_ocr": prediction.used_ocr,
        "page_count": prediction.page_count,
        "latency_ms": round(prediction.latency_ms, 3),
        "error_code": prediction.error_code,
        "document_sha256": result.document_sha256,
        "ground_truth_sha256": result.ground_truth_sha256,
    }


def _failure_payload(result: EvaluationResult) -> dict[str, object] | None:
    failures: list[dict[str, object]] = []
    invoice = result.prediction.invoice
    for field_name in HEADER_FIELDS:
        expected = getattr(result.ground_truth, field_name)
        if expected is None:
            continue
        predicted_field = getattr(invoice, field_name) if invoice is not None else None
        predicted = (
            predicted_field.value
            if predicted_field is not None
            and predicted_field.status == ExtractionStatus.EXTRACTED
            else None
        )
        if canonical_value(expected, field_name) != canonical_value(predicted, field_name):
            failures.append(
                {
                    "kind": "header_mismatch",
                    "field": field_name,
                    "expected": canonical_value(expected, field_name),
                    "predicted": canonical_value(predicted, field_name),
                }
            )
    predicted_lines = invoice.line_items if invoice is not None else []
    alignment = align_line_items(result.ground_truth.line_items, predicted_lines)
    exact = sum(pair.exact for pair in alignment)
    if exact != len(result.ground_truth.line_items) or exact != len(predicted_lines):
        failures.append(
            {
                "kind": "line_item_mismatch",
                "expected_items": len(result.ground_truth.line_items),
                "predicted_items": len(predicted_lines),
                "exact_items": exact,
            }
        )
    if result.prediction.error_code is not None:
        failures.append({"kind": "processing_error", "code": result.prediction.error_code})
    if not failures:
        return None
    return {"document_id": result.example.document_id, "failures": failures}


def _json_default(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, payloads: list[dict[str, object]]) -> None:
    lines = [json.dumps(payload, sort_keys=True, default=_json_default) for payload in payloads]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.2f}%"


def render_markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    metrics = report["metrics"]
    lines = [
        "# InvoiceOps deterministic extraction evaluation",
        "",
        f"- Extractor: `{metadata['extractor_name']}@{metadata['extractor_version']}`",
        f"- Split: `{metadata['split']}`",
        f"- Examples: {metadata['example_count']}",
        f"- Dataset fingerprint: `{metadata['dataset_fingerprint']}`",
        f"- Evaluation runtime: `{metadata['evaluation_runtime']}`",
        f"- OCR engine: `{metadata['ocr']['engine']}`",
        f"- OCR language: `{metadata['ocr']['language']}`",
        f"- OCR DPI: {metadata['ocr']['dpi']}",
        f"- OCR version: `{metadata['ocr']['version'] or 'unavailable'}`",
        "",
        "## Header fields",
        "",
        "| Field | Labeled | Extracted | Correct | Coverage | Conditional exact | Overall exact |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, field in metrics["headers"].items():
        lines.append(
            f"| {name} | {field['labeled']} | {field['extracted']} | {field['correct']} | "
            f"{_percent(field['coverage'])} | {_percent(field['conditional_exact_accuracy'])} | "
            f"{_percent(field['overall_exact_accuracy'])} |"
        )
    line_items = metrics["line_items"]
    operational = metrics["operational"]
    lines.extend(
        [
            "",
            "## Line items",
            "",
            f"- Exact item F1: {_percent(line_items['exact_f1'])}",
            f"- Field-level micro F1: {_percent(line_items['field_micro']['f1'])}",
            "- Ground-truth/predicted items: "
            f"{line_items['truth_items']}/{line_items['predicted_items']}",
            "",
            "| Field | Labeled | Correct | Accuracy |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, field in line_items["per_field"].items():
        lines.append(
            f"| {name} | {field['labeled']} | {field['tp']} | {_percent(field['accuracy'])} |"
        )
    lines.extend(
        [
            "",
            "## Operational",
            "",
            f"- Schema validity: {_percent(operational['schema_validity'])}",
            f"- Failures: {operational['failure_count']}",
            f"- OCR document rate: {_percent(operational['ocr_document_rate'])}",
            f"- Average pages ({operational['pages_known']} known): "
            f"{operational['average_pages']:.2f}",
            f"- Latency p50/p95/max (ms): {operational['latency_ms']['p50']:.3f} / "
            f"{operational['latency_ms']['p95']:.3f} / {operational['latency_ms']['max']:.3f}",
            "",
            "## Tagged slices",
            "",
            "| Slice | Documents | Schema validity | Exact item F1 |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, slice_metrics in report["slices"].items():
        lines.append(
            f"| {name} | {slice_metrics['documents']['attempted']} | "
            f"{_percent(slice_metrics['operational']['schema_validity'])} | "
            f"{_percent(slice_metrics['line_items']['exact_f1'])} |"
        )
    lines.extend(
        [
            "",
            "These are measured project results on synthetic data, not external benchmarks.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    output_dir: Path, report: dict[str, Any], results: list[EvaluationResult]
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = dict(report)
    report["metadata"] = dict(report["metadata"])
    report["metadata"]["generated_at"] = datetime.now(UTC).isoformat()
    _write_json(output_dir / "report.json", report)
    (output_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    _write_jsonl(output_dir / "predictions.jsonl", [_prediction_payload(item) for item in results])
    failures = [payload for item in results if (payload := _failure_payload(item)) is not None]
    _write_jsonl(output_dir / "failures.jsonl", failures)
