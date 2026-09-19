from typing import Protocol

from invoiceops.evaluation.schemas import EvaluationExample, GroundTruthInvoice


class EvaluationDataset(Protocol):
    examples: list[EvaluationExample]

    def read_document(self, example: EvaluationExample) -> bytes: ...

    def read_ground_truth(self, example: EvaluationExample) -> GroundTruthInvoice: ...
