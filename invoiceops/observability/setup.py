import atexit
import logging
from dataclasses import dataclass
from importlib.metadata import version
from threading import Lock
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.engine import Engine

from invoiceops.config import Settings
from invoiceops.observability.metrics import metrics as invoiceops_metrics

logger = logging.getLogger(__name__)
_lock = Lock()
_initialized_services: set[str] = set()
_providers: list[TracerProvider | MeterProvider] = []


@dataclass(frozen=True)
class ObservabilityState:
    enabled: bool
    service_name: str


def setup_observability(
    settings: Settings,
    *,
    service_name: str,
    app: Any | None = None,
    engine: Engine | None = None,
) -> ObservabilityState:
    if not settings.otel_enabled:
        return ObservabilityState(False, service_name)
    try:
        return _setup_enabled(
            settings, service_name=service_name, app=app, engine=engine
        )
    except Exception as exc:
        # Telemetry is deliberately fail-open: exporter/configuration failures must
        # never prevent invoice processing. Do not log endpoint details or payloads.
        logger.warning(
            "Telemetry initialization failed; continuing without export",
            extra={"error_type": type(exc).__name__},
        )
        return ObservabilityState(False, service_name)


def _setup_enabled(
    settings: Settings,
    *,
    service_name: str,
    app: Any | None,
    engine: Engine | None,
) -> ObservabilityState:
    with _lock:
        if service_name in _initialized_services:
            return ObservabilityState(True, service_name)
        resource = Resource.create(
            {
                "service.name": service_name,
                "deployment.environment": settings.environment,
                "service.version": version("invoiceops"),
            }
        )
        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
        # InvoiceOps owns provider shutdown below. Disabling the SDK's separate
        # atexit hooks prevents providers from being closed twice after logging
        # streams have already been torn down.
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
        )
        if not _initialized_services:
            trace.set_tracer_provider(tracer_provider)
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
            export_interval_millis=settings.otel_export_interval_seconds * 1000,
        )
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[metric_reader],
            shutdown_on_exit=False,
        )
        if not _initialized_services:
            metrics.set_meter_provider(meter_provider)
        _providers.extend((tracer_provider, meter_provider))
        invoiceops_metrics.initialize()
        if app is not None:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
        if engine is not None:
            SQLAlchemyInstrumentor().instrument(engine=engine)
        CeleryInstrumentor().instrument()  # type: ignore[no-untyped-call]
        RedisInstrumentor().instrument()
        HTTPXClientInstrumentor().instrument()
        _initialized_services.add(service_name)
        return ObservabilityState(True, service_name)


def shutdown_observability() -> None:
    with _lock:
        for provider in reversed(_providers):
            try:
                provider.shutdown()
            except Exception as exc:
                logger.warning(
                    "Telemetry provider shutdown failed",
                    extra={"error_type": type(exc).__name__},
                )
        _providers.clear()
        _initialized_services.clear()


atexit.register(shutdown_observability)
