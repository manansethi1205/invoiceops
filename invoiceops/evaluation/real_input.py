"""Offline human-labelled benchmark using the existing deterministic evaluation runner."""

import io
import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Literal, cast, get_args

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from invoiceops.evaluation.adapters.manifest import ManifestAdapter
from invoiceops.evaluation.human_annotations import HumanField, HumanInvoiceAnnotation
from invoiceops.evaluation.matching import LINE_FIELDS, align_line_items
from invoiceops.evaluation.metrics import HEADER_FIELDS, _nearest_rank
from invoiceops.evaluation.normalization import canonical_value
from invoiceops.evaluation.runner import EvaluationRunner, _length_delimited_hash
from invoiceops.evaluation.schemas import EvaluationResult
from invoiceops.extraction.errors import OcrUnavailableError, UnreadableDocumentError
from invoiceops.extraction.normalization import normalize_whitespace
from invoiceops.extraction.ocr_runtime import (
    OcrRuntimeInfo,
    OcrRuntimeUnavailableError,
    inspect_ocr_runtime,
    require_ocr_runtime,
)
from invoiceops.extraction.preprocessing import SUPPORTED_CONTENT_TYPES, DocumentTextExtractor
from invoiceops.extraction.version import EXTRACTOR_VERSION
from invoiceops.schemas.extraction import (
    DocumentText,
    EvidenceSpan,
    ExtractedField,
    ExtractionStatus,
    PageText,
    TextSource,
)

type HeaderName = Literal["invoice_number", "invoice_date", "currency", "subtotal", "tax", "total"]
type SliceName = Literal["all", "scan_or_ocr", "embedded_only", "unknown"]
type InputType = Literal["pdf", "png", "jpeg"]
type ErrorCode = Literal[
    "ocr_unavailable",
    "encrypted_document",
    "unreadable_document",
    "unsupported_document_type",
    "schema_validation_failed",
    "evaluation_failed",
]
SCORER_VERSION = "real-input-human-v1"


class Aggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Rate(Aggregate):
    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None


def ratio(numerator: int, denominator: int) -> Rate:
    return Rate(
        numerator=numerator,
        denominator=denominator,
        rate=numerator / denominator if denominator else None,
    )


class HeaderCounts(Aggregate):
    present: int
    absent: int
    not_annotated: int
    extracted_on_present: int
    value_exact: int
    supported_exact: int
    absent_abstentions: int
    false_extractions_on_absent: int
    absent_failed_documents: int
    coverage: Rate
    present_exact_accuracy: Rate
    conditional_exact_accuracy: Rate
    absent_abstention_accuracy: Rate
    annotated_exact_accuracy: Rate
    supported_present_accuracy: Rate


class Counts(Aggregate):
    attempted_documents: int
    failed_documents: int
    errors: dict[ErrorCode, int]
    schema_validity: Rate
    known_page_documents: int
    unknown_page_documents: int
    total_known_pages: int
    ocr_attempted_documents: int
    ocr_completed_documents: int
    ocr_failed_documents: int
    ocr_completed_pages: int
    input_types: dict[InputType, int]
    headers: dict[HeaderName, HeaderCounts]
    line_scored_documents: int
    line_unannotated_documents: int
    line_partial_documents: int
    labelled_rows: int
    predicted_rows: int
    line_tp: int
    line_fp: int
    line_fn: int
    line_precision: Rate
    line_recall: Rate
    line_f1: Rate
    exact_rows_with_supported_evidence: int
    latency_documents: int
    p50_latency_ms: float | None
    p95_latency_ms: float | None


class MetricDefinitions(Aggregate):
    header_coverage: Literal["extracted on present / present labels"] = (
        "extracted on present / present labels"
    )
    header_exact: Literal["canonical value exact / present labels"] = (
        "canonical value exact / present labels"
    )
    header_conditional: Literal["canonical value exact / extracted on present"] = (
        "canonical value exact / extracted on present"
    )
    absent: Literal["schema-valid abstentions / explicitly absent labels"] = (
        "schema-valid abstentions / explicitly absent labels"
    )
    unannotated: Literal["excluded, never interpreted as absent"] = (
        "excluded, never interpreted as absent"
    )
    rows: Literal[
        "order-preserving DP; all four canonical cells exact; exclude entire partial tables"
    ] = "order-preserving DP; all four canonical cells exact; exclude entire partial tables"
    line_precision: Literal["TP / (TP + FP)"] = "TP / (TP + FP)"
    line_recall: Literal["TP / (TP + FN)"] = "TP / (TP + FN)"
    line_f1: Literal["2TP / (2TP + FP + FN); empty denominator null"] = (
        "2TP / (2TP + FP + FN); empty denominator null"
    )
    failures: Literal["failed documents stay in annotated denominators; no absence credit"] = (
        "failed documents stay in annotated denominators; no absence credit"
    )
    evidence: Literal[
        "each human box center in same-page span; span text equals contained source tokens"
    ] = "each human box center in same-page span; span text equals contained source tokens"
    latency: Literal["nearest-rank milliseconds, all attempts, metadata/extraction/schema"] = (
        "nearest-rank milliseconds, all attempts, metadata/extraction/schema"
    )
    slices: Literal[
        "any OCR attempted; completed embedded only; unknown failure; mutually exclusive"
    ] = "any OCR attempted; completed embedded only; unknown failure; mutually exclusive"


class RealInputReport(Aggregate):
    # Absent on legacy input means unknown, never infer the newest scorer.
    metric_version: Literal["real-input-human-v1"] | None = None
    definitions: MetricDefinitions | None = None
    annotation_version: Literal["human-invoice-v1"]
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|unknown)$")
    source_state: Literal["clean", "working-tree changes", "unknown"]
    extractor_version: Literal["0.2.0"]
    pymupdf_version: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)+$")
    ocr_available: bool
    ocr_cli_version: str | None = Field(default=None, pattern=r"^tesseract v?[0-9]+(?:\.[0-9]+)+$")
    ocr_engine: Literal["pymupdf-tesseract"] = "pymupdf-tesseract"
    ocr_language: Literal["eng"] = "eng"
    ocr_dpi: Literal[200] = 200
    minimum_meaningful_words: int
    minimum_non_whitespace_characters: int
    slices: dict[SliceName, Counts]


def no_links(path: Path) -> None:
    for item in (path.absolute(), *path.absolute().parents):
        if item.is_symlink() or item.is_junction():
            raise ValueError("Links are not permitted")


def private_path(path: Path, repository: Path) -> Path:
    no_links(path)
    resolved = path.resolve()
    repository = repository.resolve()
    root = repository / "work" / "real-invoice-private"
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Use dedicated ignored private scratch")
    relative = resolved.relative_to(repository).as_posix()
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", relative],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    tracked = subprocess.check_output(
        ["git", "ls-files", "--", relative],
        cwd=repository,
        stderr=subprocess.DEVNULL,
    )
    if ignored.returncode != 0 or tracked.strip():
        raise ValueError("Private assets must be ignored and untracked")
    return resolved


def fresh_public(path: Path, repository: Path) -> Path:
    no_links(path)
    resolved = path.resolve()
    root = repository.resolve() / "evals" / "reports" / "real-input"
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Use a dedicated aggregate report directory")
    if resolved.exists():
        raise FileExistsError("Output directory already exists")
    return resolved


def member(root: Path, relative: Path, repository: Path) -> Path:
    if relative.is_absolute() or PureWindowsPath(str(relative)).drive or ".." in relative.parts:
        raise ValueError("Manifest paths must be contained relative paths")
    path = private_path(root / relative, repository)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Manifest member is missing or unsafe")
    return path


@contextmanager
def quiet_extraction() -> Iterator[None]:
    """Single-process CLI: discard Python and native-library payload-bearing output."""
    saved = [os.dup(1), os.dup(2)]
    sink = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(sink, 1)
        os.dup2(sink, 2)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            yield
    finally:
        for target, original in zip((1, 2), saved, strict=True):
            os.dup2(original, target)
            os.close(original)
        os.close(sink)


class ObservedTextExtractor(DocumentTextExtractor):
    """Observe existing stages; never supply synthetic words or change OCR thresholds."""

    def __init__(self, runtime: OcrRuntimeInfo) -> None:
        super().__init__(stage_context=self.stage)
        self.runtime = runtime
        self.ocr_attempted = False
        self.ocr_pages = 0
        self.page_count: int | None = None
        self.document: DocumentText | None = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if name == "ocr_fallback":
            self.ocr_attempted = True
            try:
                require_ocr_runtime(self.runtime)
            except OcrRuntimeUnavailableError:
                raise OcrUnavailableError("OCR readiness failed") from None
        yield

    def extract(self, body: bytes, content_type: str) -> DocumentText:
        # Metadata only: preserve page denominator even when OCR fails on a later page.
        try:
            with pymupdf.open(stream=body, filetype=SUPPORTED_CONTENT_TYPES[content_type]) as pdf:  # type: ignore[no-untyped-call]
                if not pdf.needs_pass:
                    self.page_count = pdf.page_count
        except (pymupdf.EmptyFileError, pymupdf.FileDataError, pymupdf.mupdf.FzErrorBase):
            pass  # Actual runner records the typed unreadable-document failure below.
        try:
            self.document = super().extract(body, content_type)
        except pymupdf.mupdf.FzErrorBase:
            # MuPDF can defer rejecting malformed image bytes until load_page(), outside
            # the production decoder's open() guard. Translate only this decoder exception.
            self.page_count = None
            raise UnreadableDocumentError("Native decoder failed") from None
        return self.document

    def _extract_page(self, page_number: int, page: pymupdf.Page) -> PageText:
        result = super()._extract_page(page_number, page)
        self.ocr_pages += int(result.source == TextSource.OCR)
        return result


@dataclass(repr=False)
class PrivateResult:
    result: EvaluationResult
    annotation: HumanInvoiceAnnotation
    observed: ObservedTextExtractor


def _inside(x: float, y: float, box: EvidenceSpan) -> bool:
    return box.bbox.x0 <= x <= box.bbox.x1 and box.bbox.y0 <= y <= box.bbox.y1


def evidence_supported(
    prediction: ExtractedField[object] | None,
    label: HumanField[object],
    document: DocumentText | None,
) -> bool:
    if document is None or prediction is None or not prediction.evidence or not label.evidence:
        return False
    for expected in label.evidence:
        found = False
        for span in prediction.evidence:
            if span.page != expected.page:
                continue
            x = (expected.bbox.x0 + expected.bbox.x1) / 2
            y = (expected.bbox.y0 + expected.bbox.y1) / 2
            if not _inside(x, y, span):
                continue
            words = [
                word.text
                for page in document.pages
                if page.page == span.page
                for word in page.words
                if word.source == span.source
                and _inside(
                    (word.bbox.x0 + word.bbox.x1) / 2, (word.bbox.y0 + word.bbox.y1) / 2, span
                )
            ]
            if words and normalize_whitespace(span.text) == normalize_whitespace(" ".join(words)):
                found = True
        if not found:
            return False
    return True


def counts(items: list[PrivateResult]) -> Counts:
    headers: dict[HeaderName, HeaderCounts] = {}
    for name in HEADER_FIELDS:
        present = absent = unannotated = extracted = exact = supported = abstentions = 0
        for item in items:
            label = getattr(item.annotation, name)
            invoice = item.result.prediction.invoice
            prediction = getattr(invoice, name) if invoice is not None else None
            value = (
                prediction.value
                if prediction is not None and prediction.status == ExtractionStatus.EXTRACTED
                else None
            )
            if label.status == "not_annotated":
                unannotated += 1
            elif label.status == "absent":
                absent += 1
                # A failed document is not credited as a successful abstention.
                abstentions += int(value is None and item.result.prediction.schema_valid)
            else:
                present += 1
                extracted += int(value is not None)
                same = value is not None and canonical_value(value, name) == canonical_value(
                    label.value,
                    name,
                )
                exact += int(same)
                supported += int(
                    same and evidence_supported(prediction, label, item.observed.document)
                )
        headers[cast(HeaderName, name)] = HeaderCounts(
            present=present,
            absent=absent,
            not_annotated=unannotated,
            extracted_on_present=extracted,
            value_exact=exact,
            supported_exact=supported,
            absent_abstentions=abstentions,
            false_extractions_on_absent=sum(
                1
                for item in items
                if getattr(item.annotation, name).status == "absent"
                and item.result.prediction.invoice is not None
                and getattr(item.result.prediction.invoice, name).status
                == ExtractionStatus.EXTRACTED
            ),
            absent_failed_documents=sum(
                getattr(item.annotation, name).status == "absent"
                and not item.result.prediction.schema_valid
                for item in items
            ),
            coverage=ratio(extracted, present),
            present_exact_accuracy=ratio(exact, present),
            conditional_exact_accuracy=ratio(exact, extracted),
            absent_abstention_accuracy=ratio(abstentions, absent),
            annotated_exact_accuracy=ratio(exact + abstentions, present + absent),
            supported_present_accuracy=ratio(supported, present),
        )
    tp = truth = predicted = line_scored = partial = unannotated_lines = supported_rows = 0
    errors: dict[ErrorCode, int] = {}
    for item in items:
        result = item.result
        if result.prediction.error_code:
            code = result.prediction.error_code
            if code not in get_args(ErrorCode.__value__):
                raise ValueError("Unknown failure code")
            safe_code = cast(ErrorCode, code)
            errors[safe_code] = errors.get(safe_code, 0) + 1
        lines = item.annotation.line_items
        if lines.status == "not_annotated":
            unannotated_lines += 1
            continue
        if any(
            getattr(row, name).status == "not_annotated"
            for row in lines.rows
            for name in LINE_FIELDS
        ):
            partial += 1
            continue
        line_scored += 1
        predictions = result.prediction.invoice.line_items if result.prediction.invoice else []
        pairs = align_line_items(result.ground_truth.line_items, predictions)
        truth += len(lines.rows)
        predicted += len(predictions)
        tp += sum(pair.exact for pair in pairs)
        for pair in pairs:
            if pair.exact and all(
                getattr(lines.rows[pair.ground_truth_index], name).status == "absent"
                or evidence_supported(
                    getattr(predictions[pair.prediction_index], name),
                    getattr(lines.rows[pair.ground_truth_index], name),
                    item.observed.document,
                )
                for name in LINE_FIELDS
            ):
                supported_rows += 1
    known = [item.observed.page_count for item in items if item.observed.page_count is not None]
    latencies = [item.result.prediction.latency_ms for item in items]
    types: dict[InputType, int] = {"pdf": 0, "png": 0, "jpeg": 0}
    for item in items:
        kind = SUPPORTED_CONTENT_TYPES[item.result.example.content_type]
        types[cast(InputType, kind)] += 1
    return Counts(
        attempted_documents=len(items),
        failed_documents=sum(errors.values()),
        errors=errors,
        schema_validity=ratio(sum(i.result.prediction.schema_valid for i in items), len(items)),
        known_page_documents=len(known),
        unknown_page_documents=len(items) - len(known),
        total_known_pages=sum(known),
        ocr_attempted_documents=sum(i.observed.ocr_attempted for i in items),
        ocr_completed_documents=sum(
            i.result.prediction.used_ocr and i.observed.document is not None for i in items
        ),
        ocr_failed_documents=sum(
            i.observed.ocr_attempted and i.observed.document is None for i in items
        ),
        ocr_completed_pages=sum(i.observed.ocr_pages for i in items),
        input_types=types,
        headers=headers,
        line_scored_documents=line_scored,
        line_unannotated_documents=unannotated_lines,
        line_partial_documents=partial,
        labelled_rows=truth,
        predicted_rows=predicted,
        line_tp=tp,
        line_fp=predicted - tp,
        line_fn=truth - tp,
        line_precision=ratio(tp, predicted),
        line_recall=ratio(tp, truth),
        line_f1=ratio(2 * tp, truth + predicted),
        exact_rows_with_supported_evidence=supported_rows,
        latency_documents=len(latencies),
        p50_latency_ms=_nearest_rank(latencies, 0.5),
        p95_latency_ms=_nearest_rank(latencies, 0.95),
    )


def source_state(
    repository: Path,
) -> tuple[str, Literal["clean", "working-tree changes", "unknown"]]:
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repository, stderr=subprocess.DEVNULL, text=True
        ).strip()
        return revision, "working-tree changes" if dirty else "clean"
    except (OSError, subprocess.SubprocessError):
        return "unknown", "unknown"


DEFINITIONS = """Value exact uses existing canonical normalization; evidence support is separate,
not DocILE location scoring. Header coverage is extracted/present; present accuracy is
value-exact/present; conditional accuracy is value-exact/extracted-on-present. Explicit absence
is correct only when a schema-valid output abstains; failed documents receive no absence credit.
Unannotated fields are excluded. Exact rows use existing order-preserving DP alignment and all
four canonical cells, including explicitly absent cells. Entire partially labelled tables are
excluded from row precision/recall, with exclusion counts. FP=predicted-TP, FN=labelled-TP,
F1=2TP/(labelled+predicted); zero denominators are null. Supported evidence additionally requires
each human box center inside a same-page predicted span with text matching its source tokens.
Scan/ocr includes any attempted OCR, including mixed PDFs and failed OCR; embedded-only requires
completed text extraction with no OCR; other failures are unknown. Latency includes failures,
nearest-rank p50/p95, metadata probing plus extraction/schema validation. Known pages include
decodable documents
even if OCR fails. OCR completed pages can include partial progress before a later failure.
OCR CLI readiness version does not identify the integrated Tesseract library version; PyMuPDF
backend version is reported separately. Human provenance is an attestation, not independently
verified authorship. Small selected private corpora are diagnostic, not population/holdout
accuracy. No model, supplier/PO discovery, matching, review, approval or payment is evaluated.
"""


def run_private_benchmark(
    manifest: Path,
    output_dir: Path,
    *,
    repository: Path,
    private_diagnostics: Path | None = None,
    allow_holdout: bool = False,
) -> RealInputReport:
    output = fresh_public(output_dir, repository)
    manifest = private_path(manifest, repository)
    if not manifest.is_file():
        raise ValueError("Private manifest is missing")
    diagnostics = private_path(private_diagnostics, repository) if private_diagnostics else None
    if diagnostics is not None and diagnostics.exists():
        raise FileExistsError("Private output already exists")
    dataset = ManifestAdapter().load(manifest)
    if dataset.examples[0].split == "holdout" and not allow_holdout:
        raise ValueError("Holdout access requires explicit opt-in")
    prepared = []
    fingerprints = []
    # Validate and read ALL inputs and human annotations before extraction or any output creation.
    for example in dataset.examples:
        body = member(manifest.parent, example.document_path, repository).read_bytes()
        labels = member(manifest.parent, example.ground_truth_path, repository).read_bytes()
        annotation = HumanInvoiceAnnotation.model_validate_json(labels)
        canonical = annotation.model_dump_json().encode()
        fingerprints.append(bytes.fromhex(_length_delimited_hash([body, canonical])))
        prepared.append((example, body, annotation, canonical))
    items = []
    with quiet_extraction():
        runtime = inspect_ocr_runtime()
        for example, body, annotation, canonical in prepared:
            observer = ObservedTextExtractor(runtime)
            runner = EvaluationRunner(text_extractor=observer)
            result = runner._evaluate(example, body, annotation.legacy_truth(), canonical)
            if observer.page_count is not None and any(
                evidence.page >= observer.page_count
                for field in [
                    *(getattr(annotation, name) for name in HEADER_FIELDS),
                    *(
                        getattr(row, name)
                        for row in annotation.line_items.rows
                        for name in LINE_FIELDS
                    ),
                ]
                for evidence in field.evidence
            ):
                raise ValueError("Human annotation page is outside the document")
            items.append(PrivateResult(result, annotation, observer))
    revision, state = source_state(repository)
    version = (
        runtime.version
        if runtime.version
        and re.fullmatch(
            r"tesseract v?[0-9]+(?:\.[0-9]+)+$",
            runtime.version,
        )
        else None
    )
    groups: dict[SliceName, list[PrivateResult]] = {
        "all": items,
        "scan_or_ocr": [i for i in items if i.observed.ocr_attempted],
        "embedded_only": [
            i for i in items if not i.observed.ocr_attempted and i.observed.document is not None
        ],
        "unknown": [
            i for i in items if not i.observed.ocr_attempted and i.observed.document is None
        ],
    }
    report = RealInputReport(
        metric_version="real-input-human-v1",
        definitions=MetricDefinitions(),
        annotation_version="human-invoice-v1",
        corpus_fingerprint=_length_delimited_hash(sorted(fingerprints)),
        source_revision=revision,
        source_state=state,
        extractor_version=EXTRACTOR_VERSION,
        pymupdf_version=pymupdf.VersionBind,
        ocr_available=runtime.available,
        ocr_cli_version=version,
        minimum_meaningful_words=8,
        minimum_non_whitespace_characters=40,
        slices={key: counts(value) for key, value in groups.items()},
    )
    output.mkdir(parents=True, exist_ok=False)
    payload = report.model_dump_json(indent=2) + "\n"
    (output / "report.json").write_text(payload, encoding="utf-8")
    (output / "report.md").write_text(
        "# Private human-labelled deterministic benchmark\n\n"
        + DEFINITIONS
        + "\n```json\n"
        + payload
        + "```\n",
        encoding="utf-8",
    )
    if diagnostics is not None:
        diagnostics.mkdir(parents=True, exist_ok=False)
        (diagnostics / "cases.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "result": i.result.model_dump(mode="json"),
                        "human_annotation": i.annotation.model_dump(mode="json"),
                    }
                )
                + "\n"
                for i in items
            ),
            encoding="utf-8",
        )
    return report
