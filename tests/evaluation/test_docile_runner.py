from typing import Any

from invoiceops.evaluation.docile_metrics import supported_f1, task_metrics


class ResultWithOmittedLir:
    task_to_docid_to_matching: dict[str, dict[str, object]] = {"kile": {}}

    def get_metrics(self, task: str, **kwargs: Any) -> dict[str, float | int]:
        del kwargs
        if task == "lir":
            raise AssertionError("omitted LIR metrics must not be requested")
        return {
            "AP": 0.5,
            "f1": 0.4,
            "precision": 0.4,
            "recall": 0.4,
            "TP": 1,
            "FP": 1,
            "FN": 2,
        }


def test_omitted_zero_prediction_task_is_reported_as_zero() -> None:
    result = ResultWithOmittedLir()

    assert task_metrics(result, "lir") == {
        "AP": 0.0,
        "f1": 0.0,
    }
    assert supported_f1(result, "lir", {"line_item_description"}) == 0.0
