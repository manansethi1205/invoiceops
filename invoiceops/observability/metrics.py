import logging
import re
import time
from collections.abc import Mapping
from threading import Lock
from typing import Any

from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import CallbackOptions, Counter, Histogram, Observation

logger = logging.getLogger(__name__)

LabelValue = str | bool

ALLOWED_LABELS: dict[str, set[str]] = {
    "http": {"method", "route", "status_class"},
    "ingestion": {"outcome", "deduplicated"},
    "jobs": {"status"},
    "extraction": {"strategy", "status"},
    "ocr": {"outcome"},
    "vlm": {"provider", "outcome"},
    "grounding": {"outcome"},
    "matching": {"mode", "decision"},
    "risk": {"disposition"},
    "review": {"event"},
    "receipt": {"event"},
}
ALLOWED_VALUES: dict[tuple[str, str], set[LabelValue]] = {
    ("http", "method"): {"GET", "POST", "PUT", "PATCH", "DELETE", "OTHER"},
    ("http", "status_class"): {"1xx", "2xx", "3xx", "4xx", "5xx"},
    ("ingestion", "outcome"): {
        "accepted",
        "unsupported_type",
        "empty",
        "too_large",
        "signature_mismatch",
    },
    ("ingestion", "deduplicated"): {True, False},
    ("jobs", "status"): {"queued", "processing", "succeeded", "failed"},
    ("extraction", "strategy"): {"deterministic-baseline", "hybrid-routed"},
    ("extraction", "status"): {"SUCCEEDED", "FAILED"},
    ("ocr", "outcome"): {"USED", "NOT_USED", "FAILED"},
    ("vlm", "provider"): {"openai", "fake", "replay"},
    ("vlm", "outcome"): {"SKIPPED", "SUCCEEDED", "FAILED"},
    ("grounding", "outcome"): {"PROMOTED", "ABSTAINED"},
    ("matching", "mode"): {"TWO_WAY", "THREE_WAY"},
    ("matching", "decision"): {"MATCHED", "NEEDS_REVIEW"},
    ("risk", "disposition"): {"CLEAR", "NEEDS_REVIEW", "NOT_ASSESSABLE"},
    ("review", "event"): {
        "CASE_OPENED",
        "CASE_CLAIMED",
        "COMMENT_ADDED",
        "CASE_RELEASED",
        "CASE_RESOLVED",
    },
    ("receipt", "event"): {"CREATED", "REPLAYED", "REVERSED"},
}
_UUID_IN_ROUTE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


def validate_labels(kind: str, labels: Mapping[str, LabelValue]) -> dict[str, LabelValue]:
    allowed = ALLOWED_LABELS[kind]
    unexpected = set(labels) - allowed
    if unexpected:
        raise ValueError(f"unbounded metric labels are forbidden: {sorted(unexpected)}")
    for label, value in labels.items():
        permitted = ALLOWED_VALUES.get((kind, label))
        if permitted is not None and value not in permitted:
            raise ValueError(f"unbounded metric label value is forbidden: {kind}.{label}")
    route = labels.get("route")
    if isinstance(route, str) and (
        len(route) > 200 or _UUID_IN_ROUTE.search(route) or not route.startswith(("/", "unmatched"))
    ):
        raise ValueError("raw or unbounded route metric label is forbidden")
    return dict(labels)


class InvoiceOpsMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._review_lock = Lock()
        self._initialized = False
        self._review_open_cases = 0
        self._review_oldest_opened_at: float | None = None

    @staticmethod
    def _dropped(exc: Exception) -> None:
        try:
            logger.warning(
                "Telemetry metric observation dropped",
                extra={"error_type": type(exc).__name__},
            )
        except Exception:
            # Logging is also observability and must never become a business dependency.
            pass

    def _observe_open_reviews(self, options: CallbackOptions) -> list[Observation]:
        del options
        with self._review_lock:
            return [Observation(self._review_open_cases)]

    def _observe_oldest_review_age(self, options: CallbackOptions) -> list[Observation]:
        del options
        with self._review_lock:
            opened_at = self._review_oldest_opened_at
        age = max(0.0, time.time() - opened_at) if opened_at is not None else 0.0
        return [Observation(age)]

    def initialize(self) -> None:
        with self._lock:
            if self._initialized:
                return
            meter = otel_metrics.get_meter("invoiceops")
            self.http_requests: Counter = meter.create_counter(
                "invoiceops_http_requests_total"
            )
            self.http_duration: Histogram = meter.create_histogram(
                "invoiceops_http_request_duration_seconds", unit="s"
            )
            self.ingestion: Counter = meter.create_counter("invoiceops_ingestion_total")
            self.jobs: Counter = meter.create_counter("invoiceops_jobs_total")
            self.queue_duration: Histogram = meter.create_histogram(
                "invoiceops_job_queue_duration_seconds", unit="s"
            )
            self.extraction: Counter = meter.create_counter("invoiceops_extraction_total")
            self.extraction_duration: Histogram = meter.create_histogram(
                "invoiceops_extraction_duration_seconds", unit="s"
            )
            self.ocr: Counter = meter.create_counter("invoiceops_ocr_total")
            self.vlm_calls: Counter = meter.create_counter("invoiceops_vlm_calls_total")
            self.vlm_duration: Histogram = meter.create_histogram(
                "invoiceops_vlm_duration_seconds", unit="s"
            )
            self.grounding: Counter = meter.create_counter("invoiceops_grounding_total")
            self.matching: Counter = meter.create_counter("invoiceops_matching_total")
            self.matching_duration: Histogram = meter.create_histogram(
                "invoiceops_matching_duration_seconds", unit="s"
            )
            self.risk: Counter = meter.create_counter("invoiceops_risk_assessments_total")
            self.review: Counter = meter.create_counter("invoiceops_review_events_total")
            self.receipt: Counter = meter.create_counter("invoiceops_receipt_events_total")
            self.open_reviews: Any = meter.create_observable_gauge(
                "invoiceops_review_open_cases", callbacks=[self._observe_open_reviews]
            )
            self.oldest_review_age: Any = meter.create_observable_gauge(
                "invoiceops_review_oldest_case_age_seconds",
                callbacks=[self._observe_oldest_review_age],
                unit="s",
            )
            self._initialized = True

    def add(self, instrument: str, kind: str, **labels: LabelValue) -> None:
        try:
            self.initialize()
            counter = getattr(self, instrument)
            counter.add(1, validate_labels(kind, labels))
        except Exception as exc:
            self._dropped(exc)

    def observe(
        self, instrument: str, value: float, kind: str, **labels: LabelValue
    ) -> None:
        try:
            self.initialize()
            histogram = getattr(self, instrument)
            histogram.record(value, validate_labels(kind, labels))
        except Exception as exc:
            self._dropped(exc)

    def set_review_backlog(self, open_cases: int, oldest_age_seconds: float) -> None:
        try:
            self.initialize()
            with self._review_lock:
                self._review_open_cases = open_cases
                self._review_oldest_opened_at = (
                    time.time() - oldest_age_seconds if open_cases > 0 else None
                )
        except Exception as exc:
            self._dropped(exc)


metrics = InvoiceOpsMetrics()
