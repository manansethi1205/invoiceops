from typing import Any, cast


def task_metrics(result: Any, task: str) -> dict[str, float | int]:
    if task not in result.task_to_docid_to_matching:
        # docile-benchmark omits a task entirely when it receives zero
        # predictions. AP and F1 are zero in that case, so preserve the empty
        # prediction set rather than inventing a placeholder field merely to
        # make the evaluator include the task.
        return {
            "AP": 0.0,
            "f1": 0.0,
        }
    return cast(dict[str, float | int], result.get_metrics(task))


def supported_f1(result: Any, task: str, fieldtypes: set[str]) -> float:
    if task not in result.task_to_docid_to_matching:
        return 0.0
    metrics = [result.get_metrics(task, fieldtype=fieldtype) for fieldtype in fieldtypes]
    true_positives = sum(int(metric["TP"]) for metric in metrics)
    false_positives = sum(int(metric["FP"]) for metric in metrics)
    false_negatives = sum(int(metric["FN"]) for metric in metrics)
    precision_denominator = true_positives + false_positives
    recall_denominator = true_positives + false_negatives
    precision = true_positives / precision_denominator if precision_denominator else 0.0
    recall = true_positives / recall_denominator if recall_denominator else 0.0
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
