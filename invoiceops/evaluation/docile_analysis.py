"""Aggregate-only DocILE diagnostics; no document text or IDs are returned."""

from collections import Counter
from typing import Any

from invoiceops.evaluation.docile_mapping import DOCILE_KILE_TO_INVOICEOPS, DOCILE_LIR_TO_INVOICEOPS
from invoiceops.schemas.extraction import Invoice


def field_counts(
    result: Any, documents: list[Any], task: str, fieldtypes: set[str]
) -> dict[str, dict[str, float | int]]:
    counts = {}
    for fieldtype in sorted(fieldtypes):
        if task in result.task_to_docid_to_matching:
            counts[fieldtype] = result.get_metrics(task, fieldtype=fieldtype)
        else:
            attribute = "fields" if task == "kile" else "li_fields"
            count = sum(
                field.fieldtype == fieldtype
                for document in documents
                for field in getattr(document.annotation, attribute)
            )
            counts[fieldtype] = {
                "TP": 0,
                "FP": 0,
                "FN": count,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "AP": 0.0,
            }
    return counts


def status_counts(invoices: list[Invoice]) -> dict[str, dict[str, int]]:
    return {
        field: dict(Counter(getattr(invoice, attribute).status.value for invoice in invoices))
        for field, attribute in DOCILE_KILE_TO_INVOICEOPS.items()
    }


def localization_counts(result: Any, task: str, fieldtypes: set[str]) -> dict[str, int]:
    """Geometric overlap is diagnostic only, not the official PCC matching metric."""
    counts: Counter[str] = Counter()
    for matching in result.task_to_docid_to_matching.get(task, {}).values():
        for prediction in matching.false_positives:
            if prediction.fieldtype not in fieldtypes:
                continue
            overlaps = any(
                gold.fieldtype == prediction.fieldtype
                and gold.page == prediction.page
                and gold.bbox.intersects(prediction.bbox)
                for gold in matching.annotations
            )
            counts[
                "unmatched_with_same_class_overlap"
                if overlaps
                else "unmatched_without_same_class_overlap"
            ] += 1
    return dict(counts)


def supported_fields(task: str) -> set[str]:
    return set(DOCILE_KILE_TO_INVOICEOPS if task == "kile" else DOCILE_LIR_TO_INVOICEOPS)
