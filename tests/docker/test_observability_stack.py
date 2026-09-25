import json
import os
import time
import uuid

import httpx
import pytest

from tests.synthetic_documents import generated_invoice_pdf

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        "PROMETHEUS_URL" not in os.environ,
        reason="Run through the observability-tests Compose service",
    ),
]


def _eventually(fetch: object, predicate: object, timeout: float = 40) -> object:
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            last = fetch()  # type: ignore[operator]
            if predicate(last):  # type: ignore[operator]
                return last
        except httpx.HTTPError:
            pass
        time.sleep(1)
    pytest.fail(f"telemetry condition was not met; last result type={type(last).__name__}")


def test_synthetic_upload_exports_correlated_safe_telemetry() -> None:
    assert os.environ.get("OBSERVABILITY_STACK_ENABLED", "false").lower() == "true", (
        "set OTEL_ENABLED=true before starting the observability profile"
    )
    invoice_number = f"OBS-{uuid.uuid4()}"
    request_id = f"observability-smoke-{uuid.uuid4().hex}"
    trace_search_start = int(time.time()) - 5
    with httpx.Client(base_url=os.environ["API_BASE_URL"], timeout=15) as api:
        upload = api.post(
            "/v1/invoices",
            headers={"X-Request-ID": request_id},
            files={
                "file": (
                    "synthetic-observability.pdf",
                    generated_invoice_pdf(invoice_number),
                    "application/pdf",
                )
            },
        )
        upload.raise_for_status()
        accepted = upload.json()

        def completed() -> bool:
            return api.get(accepted["status_url"]).json()["status"] == "succeeded"

        _eventually(completed, bool)

    with httpx.Client(base_url=os.environ["PROMETHEUS_URL"], timeout=10) as prometheus:
        metric = _eventually(
            lambda: prometheus.get(
                "/api/v1/query", params={"query": "invoiceops_ingestion_total"}
            ).json(),
            lambda value: bool(value["data"]["result"]),  # type: ignore[index]
        )
        serialized_metric = json.dumps(metric)
        assert invoice_number not in serialized_metric
        assert accepted["document_id"] not in serialized_metric

    with httpx.Client(base_url=os.environ["TEMPO_URL"], timeout=10) as tempo:
        def correlated_trace() -> dict[str, object] | None:
            query = (
                '{ resource.service.name = "invoiceops-api" '
                f'&& span.invoiceops.request_id = "{request_id}" }}'
            )
            search = tempo.get(
                "/api/search",
                params={
                    "q": query,
                    "start": trace_search_start,
                    "end": int(time.time()) + 5,
                    "limit": 10,
                },
            ).json()
            for found in search.get("traces", [])[:10]:
                detail = tempo.get(f"/api/traces/{found['traceID']}").json()
                encoded = json.dumps(detail)
                if "invoiceops-api" in encoded and "invoiceops-worker" in encoded:
                    return detail
            return None

        trace_detail = _eventually(correlated_trace, bool)
        safe_trace = json.dumps(trace_detail)
        assert invoice_number not in safe_trace
        assert "Industrial Filter" not in safe_trace

    with httpx.Client(base_url=os.environ["GRAFANA_URL"], timeout=10) as grafana:
        datasources = _eventually(
            lambda: grafana.get("/api/datasources").json(),
            lambda value: {item["name"] for item in value} >= {"Prometheus", "Tempo"},
        )
        assert {item["name"] for item in datasources} >= {  # type: ignore[union-attr]
            "Prometheus",
            "Tempo",
        }
        dashboards = _eventually(
            lambda: grafana.get(
                "/api/search", params={"query": "InvoiceOps Operations"}
            ).json(),
            lambda value: any(item["uid"] == "invoiceops-operations" for item in value),
        )
        assert any(
            item["uid"] == "invoiceops-operations" for item in dashboards  # type: ignore[union-attr]
        )
