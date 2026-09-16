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
    "request_path",
    "status_code",
    "duration_ms",
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
        for field in STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
