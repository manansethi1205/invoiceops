import math
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from invoiceops.evaluation.matching import (
    LINE_FIELDS,
    align_line_items,
    predicted_line_value,
)
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.schemas import EvaluationResult
from invoiceops.schemas.extraction import ExtractionStatus

HEADER_FIELDS = ("invoice_number", "invoice_date", "currency", "subtotal", "tax", "total")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def calculate_metrics(results: Iterable[EvaluationResult]) -> dict[str, Any]:
    items = list(results)
    headers: dict[str, dict[str, int | float | None]] = {}
    for field_name in HEADER_FIELDS:
        labeled = extracted = correct = 0
        for result in items:
            truth = getattr(result.ground_truth, field_name)
            if truth is None:
                continue
            labeled += 1
            if result.prediction.invoice is None:
                continue
            prediction = getattr(result.prediction.invoice, field_name)
            if prediction.status != ExtractionStatus.EXTRACTED or prediction.value is None:
                continue
            extracted += 1
            if canonical_value(truth, field_name) == canonical_value(
                prediction.value, field_name
            ):
                correct += 1
        headers[field_name] = {
            "labeled": labeled,
            "extracted": extracted,
            "correct": correct,
            "coverage": _ratio(extracted, labeled),
            "conditional_exact_accuracy": _ratio(correct, extracted),
            "overall_exact_accuracy": _ratio(correct, labeled),
        }

    exact_tp = truth_items = predicted_items = 0
    field_counts = {name: {"tp": 0, "fp": 0, "fn": 0, "labeled": 0} for name in LINE_FIELDS}
    for result in items:
        truth_lines = result.ground_truth.line_items
        predicted_lines = result.prediction.invoice.line_items if result.prediction.invoice else []
        pairs = align_line_items(truth_lines, predicted_lines)
        pair_by_truth = {pair.ground_truth_index: pair for pair in pairs}
        paired_predictions = {pair.prediction_index for pair in pairs}
        exact_tp += sum(pair.exact for pair in pairs)
        truth_items += len(truth_lines)
        predicted_items += len(predicted_lines)
        for truth_index, truth_line in enumerate(truth_lines):
            pair = pair_by_truth.get(truth_index)
            for field_name in LINE_FIELDS:
                truth_value = getattr(truth_line, field_name)
                if truth_value is not None:
                    field_counts[field_name]["labeled"] += 1
                predicted_value = (
                    predicted_line_value(predicted_lines[pair.prediction_index], field_name)
                    if pair is not None
                    else None
                )
                equal = canonical_value(truth_value, field_name) == canonical_value(
                    predicted_value, field_name
                )
                if truth_value is not None and predicted_value is not None and equal:
                    field_counts[field_name]["tp"] += 1
                else:
                    if truth_value is not None:
                        field_counts[field_name]["fn"] += 1
                    if predicted_value is not None:
                        field_counts[field_name]["fp"] += 1
        for prediction_index, predicted_line in enumerate(predicted_lines):
            if prediction_index in paired_predictions:
                continue
            for field_name in LINE_FIELDS:
                if predicted_line_value(predicted_line, field_name) is not None:
                    field_counts[field_name]["fp"] += 1

    total_tp = sum(counts["tp"] for counts in field_counts.values())
    total_fp = sum(counts["fp"] for counts in field_counts.values())
    total_fn = sum(counts["fn"] for counts in field_counts.values())
    exact_precision = _ratio(exact_tp, predicted_items)
    exact_recall = _ratio(exact_tp, truth_items)
    micro_precision = _ratio(total_tp, total_tp + total_fp)
    micro_recall = _ratio(total_tp, total_tp + total_fn)
    latencies = [result.prediction.latency_ms for result in items]
    page_counts = [
        result.prediction.page_count
        for result in items
        if result.prediction.page_count is not None
    ]
    attempted = len(items)
    valid = sum(result.prediction.schema_valid for result in items)
    ocr = sum(result.prediction.used_ocr for result in items)
    error_counts: dict[str, int] = defaultdict(int)
    for result in items:
        if result.prediction.error_code is not None:
            error_counts[result.prediction.error_code] += 1
    line_fields: dict[str, dict[str, int | float | None]] = {}
    for name, counts in field_counts.items():
        line_fields[name] = {
            **counts,
            "accuracy": _ratio(counts["tp"], counts["labeled"]),
        }
    return {
        "documents": {"attempted": attempted, "schema_valid": valid},
        "headers": headers,
        "line_items": {
            "truth_items": truth_items,
            "predicted_items": predicted_items,
            "exact_true_positives": exact_tp,
            "exact_precision": exact_precision,
            "exact_recall": exact_recall,
            "exact_f1": _f1(exact_precision, exact_recall),
            "field_micro": {
                "tp": total_tp,
                "fp": total_fp,
                "fn": total_fn,
                "precision": micro_precision,
                "recall": micro_recall,
                "f1": _f1(micro_precision, micro_recall),
            },
            "per_field": line_fields,
        },
        "operational": {
            "schema_validity": _ratio(valid, attempted),
            "failure_count": attempted - valid,
            "error_counts": dict(sorted(error_counts.items())),
            "ocr_documents": ocr,
            "ocr_document_rate": _ratio(ocr, attempted),
            "pages_known": len(page_counts),
            "average_pages": (
                sum(page_counts) / len(page_counts) if page_counts else None
            ),
            "latency_ms": {
                "count": len(latencies),
                "p50": _nearest_rank(latencies, 0.50),
                "p95": _nearest_rank(latencies, 0.95),
                "max": max(latencies, default=None),
            },
        },
    }


def calculate_tagged_slices(results: list[EvaluationResult]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[EvaluationResult]] = defaultdict(list)
    for result in results:
        for key, value in sorted(result.example.tags.items()):
            groups[f"{key}={value}"].append(result)
    return {name: calculate_metrics(group) for name, group in sorted(groups.items())}
