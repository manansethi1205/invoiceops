import importlib
import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import context, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags

from invoiceops.config import Settings
from invoiceops.db import engine
from invoiceops.health import PROBE_TIMEOUT_SECONDS
from invoiceops.ingestion.dispatch import CeleryJobDispatcher
from invoiceops.ingestion.service import IngestionService, UnsupportedDocumentError, UploadCommand
from invoiceops.ingestion.storage import S3ObjectStore
from invoiceops.logging import JsonFormatter
from invoiceops.observability.context import reset_request_id, set_request_id
from invoiceops.observability.metrics import InvoiceOpsMetrics, validate_labels
from invoiceops.observability.setup import setup_observability


def test_disabled_observability_is_noop_and_idempotent() -> None:
    settings = Settings(otel_enabled=False)
    first = setup_observability(settings, service_name="test-service")
    second = setup_observability(settings, service_name="test-service")
    assert first == second
    assert first.enabled is False


def test_enabled_initialization_reuses_existing_service_state() -> None:
    setup_module = importlib.import_module("invoiceops.observability.setup")
    setup_module._initialized_services.add("already-initialized")
    try:
        state = setup_module.setup_observability(
            Settings(otel_enabled=True), service_name="already-initialized"
        )
    finally:
        setup_module._initialized_services.discard("already-initialized")
    assert state.enabled is True


def test_telemetry_initialization_failure_is_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_module = importlib.import_module("invoiceops.observability.setup")

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic exporter failure")

    monkeypatch.setattr(setup_module, "_setup_enabled", fail)
    state = setup_module.setup_observability(
        Settings(otel_enabled=True), service_name="synthetic-service"
    )
    assert state.enabled is False


def test_provider_shutdown_is_idempotent() -> None:
    setup_module = importlib.import_module("invoiceops.observability.setup")

    class RecordingProvider:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    provider = RecordingProvider()
    setup_module._providers.append(provider)

    setup_module.shutdown_observability()
    setup_module.shutdown_observability()

    assert provider.shutdown_calls == 1


def test_runtime_metric_failures_are_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = InvoiceOpsMetrics()

    def fail() -> None:
        raise RuntimeError("synthetic recorder failure")

    monkeypatch.setattr(runtime, "initialize", fail)
    runtime.add("ingestion", "ingestion", outcome="accepted", deduplicated=False)
    runtime.observe(
        "extraction_duration",
        1.0,
        "extraction",
        strategy="deterministic-baseline",
        status="SUCCEEDED",
    )
    runtime.set_review_backlog(1, 60.0)


def test_review_age_advances_at_collection_time(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_module = importlib.import_module("invoiceops.observability.metrics")
    runtime = InvoiceOpsMetrics()
    monkeypatch.setattr(metrics_module.time, "time", lambda: 1_000.0)
    runtime.set_review_backlog(2, 100.0)
    monkeypatch.setattr(metrics_module.time, "time", lambda: 1_100.0)

    observations = runtime._observe_oldest_review_age(None)  # type: ignore[arg-type]
    assert observations[0].value == 200.0


def test_unused_otel_endpoint_is_not_validated() -> None:
    disabled = Settings(otel_enabled=False, otel_exporter_otlp_endpoint="not-a-url")
    assert disabled.otel_enabled is False
    with pytest.raises(ValueError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        Settings(otel_enabled=True, otel_exporter_otlp_endpoint="not-a-url")


def test_worker_prefork_hooks_initialize_and_shutdown_child_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    celery_module = importlib.import_module("workers.extraction.celery_app")
    calls: list[tuple[str, str | None]] = []

    def record_setup(
        settings: Settings, *, service_name: str, engine: object
    ) -> None:
        del settings, engine
        calls.append(("setup", service_name))

    def record_shutdown() -> None:
        calls.append(("shutdown", None))

    monkeypatch.setattr(celery_module, "setup_observability", record_setup)
    monkeypatch.setattr(celery_module, "shutdown_observability", record_shutdown)

    celery_module._initialize_worker_telemetry(signal="worker_process_init")
    celery_module._shutdown_worker_telemetry(signal="worker_process_shutdown")

    assert calls == [("setup", "invoiceops-worker"), ("shutdown", None)]


def test_sdk_exports_safe_span_parentage(monkeypatch: pytest.MonkeyPatch) -> None:
    tracing_module = importlib.import_module("invoiceops.observability.tracing")
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "sdk-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing_module.trace, "get_tracer", provider.get_tracer)

    with tracing_module.span("invoiceops.parent", {"safe.kind": "test"}):
        with tracing_module.span("invoiceops.child", outcome="ok"):
            pass

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert spans["invoiceops.child"].parent is not None
    assert spans["invoiceops.child"].parent.span_id == spans["invoiceops.parent"].context.span_id
    assert spans["invoiceops.parent"].attributes == {"safe.kind": "test"}
    assert spans["invoiceops.child"].attributes == {"outcome": "ok"}
    assert spans["invoiceops.parent"].resource.attributes["service.name"] == "sdk-test"
    provider.shutdown()


def test_fastapi_instrumentation_exports_one_server_span() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "fastapi-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    test_app = FastAPI()

    @test_app.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    FastAPIInstrumentor.instrument_app(test_app, tracer_provider=provider)
    try:
        with TestClient(test_app) as test_client:
            assert test_client.get("/probe").status_code == 200
        server_spans = [
            span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER
        ]
        assert len(server_spans) == 1
        assert server_spans[0].attributes["http.route"] == "/probe"
        assert server_spans[0].resource.attributes["service.name"] == "fastapi-test"
    finally:
        FastAPIInstrumentor.uninstrument_app(test_app)
        provider.shutdown()


def test_sdk_exports_metric_name_labels_and_value(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_module = importlib.import_module("invoiceops.observability.metrics")
    reader = InMemoryMetricReader()
    provider = MeterProvider(
        resource=Resource.create({"service.name": "sdk-test"}), metric_readers=[reader]
    )
    monkeypatch.setattr(metrics_module.otel_metrics, "get_meter", provider.get_meter)
    runtime = InvoiceOpsMetrics()
    runtime.add("ingestion", "ingestion", outcome="accepted", deduplicated=False)

    data = reader.get_metrics_data()
    assert data is not None
    metrics_by_name = {
        metric.name: metric
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }
    points = list(metrics_by_name["invoiceops_ingestion_total"].data.data_points)
    assert len(points) == 1
    assert points[0].value == 1
    assert dict(points[0].attributes) == {"outcome": "accepted", "deduplicated": False}
    assert data.resource_metrics[0].resource.attributes["service.name"] == "sdk-test"
    provider.shutdown()


@pytest.mark.parametrize(
    "forbidden",
    ["document_id", "job_id", "invoice_number", "vendor_name", "reviewer_id", "filename"],
)
def test_forbidden_business_values_cannot_be_metric_labels(forbidden: str) -> None:
    with pytest.raises(ValueError, match="unbounded metric labels"):
        validate_labels("ingestion", {"outcome": "accepted", forbidden: "secret"})


def test_raw_identifier_route_cannot_be_metric_label() -> None:
    with pytest.raises(ValueError, match="raw or unbounded route"):
        validate_labels(
            "http",
            {
                "method": "GET",
                "route": "/v1/jobs/742ed240-7246-4d2f-847f-8649b3ea79dc",
                "status_class": "2xx",
            },
        )


def test_ingestion_validation_exception_records_failure_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = importlib.import_module("invoiceops.ingestion.service")
    recorded: list[dict[str, object]] = []

    class RecordingMetrics:
        def add(self, instrument: str, kind: str, **labels: object) -> None:
            recorded.append({"instrument": instrument, "kind": kind, **labels})

    monkeypatch.setattr(service_module, "metrics", RecordingMetrics())
    service = IngestionService(
        session=None,  # type: ignore[arg-type]
        object_store=None,  # type: ignore[arg-type]
        dispatcher=None,  # type: ignore[arg-type]
        max_upload_bytes=10,
    )
    with pytest.raises(UnsupportedDocumentError):
        service.ingest(UploadCommand("unsafe.txt", "text/plain", b"content"))
    assert recorded == [
        {
            "instrument": "ingestion",
            "kind": "ingestion",
            "outcome": "unsupported_type",
            "deduplicated": False,
        }
    ]


def test_json_logs_include_request_trace_and_span_correlation() -> None:
    request_token = set_request_id("request-safe-1")
    span_context = SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
        trace_state=trace.TraceState(),
    )
    context_token = context.attach(trace.set_span_in_context(NonRecordingSpan(span_context)))
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "ok", (), None)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        context.detach(context_token)
        reset_request_id(request_token)
    assert payload["request_id"] == "request-safe-1"
    assert payload["trace_id"] == f"{1:032x}"
    assert payload["span_id"] == f"{2:016x}"


def test_request_ids_are_generated_preserved_and_invalid_replaced(client: TestClient) -> None:
    generated = client.get("/health/live")
    assert uuid.UUID(generated.headers["X-Request-ID"])

    preserved = client.get("/health/live", headers={"X-Request-ID": "caller-123"})
    assert preserved.headers["X-Request-ID"] == "caller-123"

    invalid = client.get("/health/live", headers={"X-Request-ID": "bad value" * 30})
    assert invalid.headers["X-Request-ID"] != "bad value" * 30
    assert uuid.UUID(invalid.headers["X-Request-ID"])


def test_request_log_uses_route_template_not_uuid(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = importlib.import_module("apps.api.main")
    captured: dict[str, object] = {}

    def capture(message: str, *, extra: dict[str, object]) -> None:
        captured.update(extra)

    monkeypatch.setattr(api.logger, "info", capture)
    identifier = str(uuid.uuid4())
    response = client.get(f"/v1/jobs/{identifier}")
    assert response.status_code == 404
    assert captured["route_template"] == "/v1/jobs/{job_id}"
    assert identifier not in str(captured["route_template"])


def test_liveness_does_not_depend_on_readiness(client: TestClient) -> None:
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_readiness_is_healthy_when_all_dependencies_respond(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = importlib.import_module("apps.api.main")
    monkeypatch.setattr(
        api,
        "dependency_status",
        lambda settings: {
            "postgresql": "ready",
            "redis": "ready",
            "object_storage": "ready",
        },
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert set(response.json()["components"].values()) == {"ready"}


def test_business_clients_do_not_inherit_probe_timeouts() -> None:
    assert engine.pool.timeout() > PROBE_TIMEOUT_SECONDS  # type: ignore[attr-defined]
    store = S3ObjectStore(Settings(s3_endpoint_url="http://object-storage.invalid"))
    assert store.client.meta.config.connect_timeout > PROBE_TIMEOUT_SECONDS
    assert store.client.meta.config.read_timeout > PROBE_TIMEOUT_SECONDS


def test_database_readiness_uses_a_disposable_bounded_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    health_module = importlib.import_module("invoiceops.health")
    captured: dict[str, object] = {}

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, statement: object) -> None:
            captured["statement"] = statement

    class ProbeEngine:
        def connect(self) -> Connection:
            return Connection()

        def dispose(self) -> None:
            captured["disposed"] = True

    def create_probe(url: str, **options: object) -> ProbeEngine:
        captured.update({"url": url, **options})
        return ProbeEngine()

    monkeypatch.setattr(health_module, "create_engine", create_probe)
    health_module.check_database(
        Settings(database_url="postgresql+psycopg://user:password@database/invoiceops")
    )

    assert captured["pool_timeout"] == PROBE_TIMEOUT_SECONDS
    assert captured["connect_args"] == {"connect_timeout": PROBE_TIMEOUT_SECONDS}
    assert captured["disposed"] is True


def test_celery_dispatch_propagates_request_id() -> None:
    captured: dict[str, object] = {}

    class RecordingSender:
        def send_task(
            self,
            name: str,
            *,
            args: list[str],
            headers: dict[str, str] | None,
        ) -> object:
            captured.update({"name": name, "args": args, "headers": headers})
            return object()

    token = set_request_id("correlation-42")
    try:
        CeleryJobDispatcher(RecordingSender()).enqueue("job-1")
    finally:
        reset_request_id(token)
    assert captured == {
        "name": "invoiceops.process_document",
        "args": ["job-1"],
        "headers": {"x-request-id": "correlation-42"},
    }
