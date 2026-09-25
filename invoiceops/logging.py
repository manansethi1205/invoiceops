import json
import logging
from datetime import UTC, datetime
from typing import Any

STRUCTURED_FIELDS = (
    "event",
    "job_id",
    "document_id",
    "sha256",
    "status",
    "deduplicated",
    "byte_size",
    "content_type",
    "retry_count",
    "error_code",
    "request_method",
    "status_code",
    "duration_ms",
    "error_type",
    "request_id",
    "trace_id",
    "span_id",
    "route_template",
    "matching_mode",
    "decision",
    "strategy",
    "provider",
    "outcome",
)


class JsonFormatter(logging.Formatter):
    """Render one machine-parseable JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        from invoiceops.observability.context import get_request_id
        from invoiceops.observability.tracing import trace_identifiers

        trace_id, span_id = trace_identifiers()
        correlation = {
            "request_id": get_request_id(),
            "trace_id": trace_id,
            "span_id": span_id,
        }
        for field, value in correlation.items():
            if value is not None:
                payload[field] = value
        for field in STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["error_type"] = exception_type.__name__
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
