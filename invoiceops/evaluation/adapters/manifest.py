import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter

from invoiceops.evaluation.schemas import EvaluationExample, GroundTruthInvoice

_EXAMPLES = TypeAdapter(list[EvaluationExample])


@dataclass(frozen=True)
class ManifestDataset:
    manifest_path: Path
    manifest_bytes: bytes
    examples: list[EvaluationExample]

    def _resolve(self, relative_path: Path) -> Path:
        return (self.manifest_path.parent / relative_path).resolve()

    def read_document(self, example: EvaluationExample) -> bytes:
        return self._resolve(example.document_path).read_bytes()

    def read_ground_truth_bytes(self, example: EvaluationExample) -> bytes:
        return self._resolve(example.ground_truth_path).read_bytes()

    def read_ground_truth(self, example: EvaluationExample) -> GroundTruthInvoice:
        return GroundTruthInvoice.model_validate_json(self.read_ground_truth_bytes(example))


class ManifestAdapter:
    def load(self, manifest_path: Path) -> ManifestDataset:
        path = manifest_path.resolve()
        raw = path.read_bytes()
        records: list[object] = []
        for line_number, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on manifest line {line_number}") from exc
        examples = _EXAMPLES.validate_python(records)
        if not examples:
            raise ValueError("evaluation manifest is empty")
        document_ids = [example.document_id for example in examples]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("evaluation manifest contains duplicate document_id values")
        splits = {example.split for example in examples}
        if len(splits) != 1:
            raise ValueError("evaluation manifest must contain exactly one split")
        return ManifestDataset(path, raw, examples)
