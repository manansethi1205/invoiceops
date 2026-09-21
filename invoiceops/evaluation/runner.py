import hashlib
import json
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path

import pymupdf
from pydantic import ValidationError

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.metrics import calculate_metrics, calculate_tagged_slices
from invoiceops.evaluation.schemas import (
    EvaluationExample,
    EvaluationPrediction,
    EvaluationResult,
    GroundTruthInvoice,
)
from invoiceops.extraction.errors import (
    DocumentExtractionError,
    EncryptedDocumentError,
    OcrUnavailableError,
    UnreadableDocumentError,
    UnsupportedDocumentTypeError,
)
from invoiceops.extraction.ocr_runtime import (
    OcrRuntimeInfo,
    inspect_ocr_runtime,
    require_ocr_runtime,
)
from invoiceops.extraction.pipeline import DeterministicInvoiceExtractor
from invoiceops.extraction.preprocessing import DocumentTextExtractor
from invoiceops.schemas.extraction import Invoice


class HoldoutAccessError(ValueError):
    pass


def _length_delimited_hash(components: list[bytes]) -> str:
    digest = hashlib.sha256()
    for component in components:
        digest.update(len(component).to_bytes(8, "big"))
        digest.update(component)
    return digest.hexdigest()


def _canonical_ground_truth(truth: GroundTruthInvoice) -> bytes:
    payload = truth.model_dump(mode="json")
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


type PreparedExample = tuple[EvaluationExample, bytes, GroundTruthInvoice, bytes]


def _dataset_fingerprint(manifest_bytes: bytes, inputs: list[PreparedExample]) -> str:
    components = [manifest_bytes]
    for _, document_bytes, _, canonical_truth in inputs:
        components.append(document_bytes)
        components.append(canonical_truth)
    return _length_delimited_hash(components)


def _error_code(exc: Exception) -> str:
    if isinstance(exc, OcrUnavailableError):
        return "ocr_unavailable"
    if isinstance(exc, EncryptedDocumentError):
        return "encrypted_document"
    if isinstance(exc, UnreadableDocumentError):
        return "unreadable_document"
    if isinstance(exc, UnsupportedDocumentTypeError):
        return "unsupported_document_type"
    if isinstance(exc, ValidationError):
        return "schema_validation_failed"
    return "evaluation_failed"


class EvaluationRunner:
    def __init__(
        self,
        *,
        text_extractor: DocumentTextExtractor | None = None,
        invoice_extractor: DeterministicInvoiceExtractor | None = None,
        clock: Callable[[], float] = time.perf_counter,
        ocr_runtime_probe: Callable[[], OcrRuntimeInfo] = inspect_ocr_runtime,
    ) -> None:
        self.text_extractor = text_extractor or DocumentTextExtractor()
        self.invoice_extractor = invoice_extractor or DeterministicInvoiceExtractor()
        self.clock = clock
        self.ocr_runtime_probe = ocr_runtime_probe

    def run(
        self, manifest_path: Path, *, allow_holdout: bool = False
    ) -> tuple[dict[str, object], list[EvaluationResult]]:
        dataset = ManifestAdapter().load(manifest_path)
        split = dataset.examples[0].split
        if split == "holdout" and not allow_holdout:
            raise HoldoutAccessError(
                "Holdout evaluation is disabled. Re-run with --allow-holdout."
            )
        ocr_runtime = self.ocr_runtime_probe()
        if any(example.tags.get("source") == "ocr" for example in dataset.examples):
            require_ocr_runtime(ocr_runtime)
        inputs = [
            (
                example,
                dataset.read_document(example),
                (truth := dataset.read_ground_truth(example)),
                _canonical_ground_truth(truth),
            )
            for example in dataset.examples
        ]
        results = [self._evaluate(*prepared) for prepared in inputs]
        fingerprint = _dataset_fingerprint(dataset.manifest_bytes, inputs)
        report: dict[str, object] = {
            "metadata": {
                "extractor_name": self.invoice_extractor.name,
                "extractor_version": self.invoice_extractor.version,
                "split": split,
                "example_count": len(results),
                "dataset_fingerprint": fingerprint,
                "manifest_sha256": hashlib.sha256(dataset.manifest_bytes).hexdigest(),
                "python_version": platform.python_version(),
                "pymupdf_version": pymupdf.VersionBind,
                "evaluation_runtime": os.environ.get(
                    "INVOICEOPS_EVALUATION_RUNTIME", "local"
                ),
                "ocr": {
                    "engine": ocr_runtime.engine,
                    "available": ocr_runtime.available,
                    "version": ocr_runtime.version,
                    "language": "eng",
                    "dpi": 200,
                },
                "configuration": {
                    "minimum_meaningful_words": self.text_extractor.minimum_meaningful_words,
                    "minimum_non_whitespace_characters": (
                        self.text_extractor.minimum_non_whitespace_characters
                    ),
                    "line_item_alignment": "order_preserving_dp_v1",
                },
            },
            "metrics": calculate_metrics(results),
            "slices": calculate_tagged_slices(results),
        }
        return report, results

    def _evaluate(
        self,
        parsed_example: EvaluationExample,
        document_bytes: bytes,
        truth: GroundTruthInvoice,
        canonical_truth: bytes,
    ) -> EvaluationResult:
        started = self.clock()
        invoice: Invoice | None = None
        schema_valid = False
        used_ocr = False
        page_count: int | None = None
        error_code: str | None = None
        try:
            document = self.text_extractor.extract(document_bytes, parsed_example.content_type)
            used_ocr = document.used_ocr
            page_count = len(document.pages)
            extracted = self.invoice_extractor.extract(document)
            invoice = Invoice.model_validate(extracted.model_dump(mode="python"))
            schema_valid = True
        except (DocumentExtractionError, ValidationError) as exc:
            error_code = _error_code(exc)
            used_ocr = isinstance(exc, OcrUnavailableError)
        latency_ms = max(0.0, (self.clock() - started) * 1000)
        return EvaluationResult(
            example=parsed_example,
            ground_truth=truth,
            prediction=EvaluationPrediction(
                document_id=parsed_example.document_id,
                invoice=invoice,
                schema_valid=schema_valid,
                used_ocr=used_ocr,
                page_count=page_count,
                latency_ms=latency_ms,
                error_code=error_code,
            ),
            document_sha256=hashlib.sha256(document_bytes).hexdigest(),
            ground_truth_sha256=hashlib.sha256(canonical_truth).hexdigest(),
        )
