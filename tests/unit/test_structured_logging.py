import json
import logging

from invoiceops.logging import JsonFormatter


def test_json_formatter_emits_machine_readable_context() -> None:
    record = logging.LogRecord(
        name="invoiceops.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Invoice accepted",
        args=(),
        exc_info=None,
    )
    record.event = "ingestion.accepted"
    record.job_id = "job-123"
    record.deduplicated = False

    payload = json.loads(JsonFormatter().format(record))

    assert payload["level"] == "INFO"
    assert payload["message"] == "Invoice accepted"
    assert payload["event"] == "ingestion.accepted"
    assert payload["job_id"] == "job-123"
    assert payload["deduplicated"] is False
    assert payload["timestamp"].endswith("+00:00")

