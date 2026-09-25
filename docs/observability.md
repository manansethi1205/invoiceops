# Observability and demonstration SLOs

## Architecture and local startup

InvoiceOps emits OpenTelemetry from the FastAPI process (`invoiceops-api`) and Celery process
(`invoiceops-worker`). OTLP/HTTP reaches the Collector, which sends traces to Tempo and exposes
metrics for Prometheus. Grafana has provisioned Prometheus and Tempo data sources plus the
`InvoiceOps Operations` dashboard.

```text
API -- trace context --> Celery worker -- OTLP --> Collector --> Tempo
                                      metrics --> Collector --> Prometheus --> Grafana
```

Telemetry is disabled by default. For synthetic local use:

```powershell
Copy-Item .env.example .env -Force
$env:OTEL_ENABLED = "true"
$env:COMPOSE_PARALLEL_LIMIT = "1"
$env:COMPOSE_BAKE = "false"
docker compose --profile observability pull postgres redis object-storage otel-collector tempo prometheus grafana
docker compose --progress plain --profile observability build api
docker compose --profile observability up --no-build -d --wait --wait-timeout 180 api worker otel-collector tempo prometheus grafana
Invoke-RestMethod http://localhost:8000/health/live
Invoke-RestMethod http://localhost:8000/health/ready
Start-Process http://localhost:3000
```

Run the synthetic telemetry smoke test without treating successful one-shot migrations as a test
failure:

```powershell
$env:COMPOSE_PARALLEL_LIMIT = "1"
$env:COMPOSE_BAKE = "false"
docker compose --progress plain --profile observability build api
docker compose --progress plain --profile observability build observability-tests
docker compose --profile observability up --no-build -d --wait --wait-timeout 180 api worker otel-collector tempo prometheus grafana
docker compose --profile observability run --rm --no-deps observability-tests
```

Build `api` even when `observability-tests` is already present: the application and test images use
different local tags. Local images use `pull_policy: never`, so a missing image produces a direct
build error instead of an unrelated registry authentication attempt.

Exporter startup and delivery failures are fail-open and cannot change business transactions.
Shutdown flushes configured providers. `/health/live` never contacts dependencies; readiness uses
short PostgreSQL, Redis and object-store probes and returns `503` if any is unavailable.

## Trace inventory

Automatic spans cover FastAPI, SQLAlchemy, Celery, Redis and outbound HTTP. Safe custom spans cover
object storage, ingestion transaction/dispatch, preprocessing, deterministic extraction, hybrid
routing, provider call, grounding/fusion, PO locking, matching context and engine, allocation
reconciliation, duplicate risk, review routing, and transaction commit. Attributes are limited to
bounded strategy, mode, status, decision, outcome, provider, and event categories.

FastAPI owns the single HTTP `SERVER` span; request middleware adds correlation, safe logs and
bounded metrics without creating a second request span. Celery initializes exporters inside each
prefork child and flushes them on child shutdown.

## Metric inventory

| Metric | Labels | Operational question |
| --- | --- | --- |
| `invoiceops_http_requests_total` / `invoiceops_http_request_duration_seconds` | `method`, `route`, `status_class` | Is an API route slow or failing? |
| `invoiceops_ingestion_total` | `outcome`, `deduplicated` | Are uploads accepted or failing? |
| `invoiceops_jobs_total` | `status` | Where do background jobs end? |
| `invoiceops_job_queue_duration_seconds` | none | Is queue delay growing? |
| `invoiceops_extraction_total` | `strategy`, `status` | Which extraction path succeeds? |
| `invoiceops_extraction_duration_seconds` | `strategy`, `status` | Which extraction path is slow? |
| `invoiceops_ocr_total` | `outcome` | How often does OCR run? |
| `invoiceops_vlm_calls_total` / `invoiceops_vlm_duration_seconds` | `provider`, `outcome` | Is the optional provider failing or slow? |
| `invoiceops_grounding_total` | `outcome` | Are candidates promoted or abstained? |
| `invoiceops_matching_total` / `invoiceops_matching_duration_seconds` | `mode`, `decision` | Which match modes require review? |
| `invoiceops_risk_assessments_total` | `disposition` | How does duplicate risk route? |
| `invoiceops_review_events_total` | `event` | How is review work progressing? |
| `invoiceops_receipt_events_total` | `event` | Are receipt mutations occurring? |
| `invoiceops_review_open_cases` | none | Is backlog growing? |
| `invoiceops_review_oldest_case_age_seconds` | none | Is review aging? |

Review backlog instruments are observable gauges. The oldest-case age is calculated at collection
time from the last committed backlog snapshot, so it continues increasing even when the review API
is idle.

IDs, paths, filenames, vendor/invoice/PO values, reviewer IDs, trace IDs and errors are forbidden as
metric labels. The code rejects unexpected label keys. IDs may appear only where necessary in
correlated application logs and traces, never as dimensions.

## Privacy policy

Telemetry must never contain document bytes, invoice/OCR text, evidence quotes, filenames, vendor
names, invoice or PO numbers, prompts, credentials, or exception messages. Request logs use route
templates rather than UUID-bearing raw paths. Request IDs are restricted to a short safe character
set; invalid values are replaced. The checked-in stack is only for synthetic/de-identified data.

## Demonstration objectives

These are proposed demo objectives, not measured production guarantees:

| Objective | Target |
| --- | ---: |
| API availability | 99% |
| Upload API p95 | 500 ms |
| Matching API p95 | 750 ms |
| Extraction success | 99% |
| Queue wait p95 | 10 s |
| Known false auto-match count | 0 |
| Oldest review case | under 24 h |

Local synthetic observations must be reported separately from these targets. There are currently
no production measurements or production SLO claims.

## Troubleshooting

- A `503` from readiness includes only `ready`/`unavailable` component states. Check service logs;
  connection strings are intentionally omitted.
- If Grafana is empty, confirm `OTEL_ENABLED=true`, then query `up` and an `invoiceops_*` metric in
  Prometheus.
- If traces are absent, inspect Collector and Tempo logs and verify the API and worker use the same
  Collector endpoint. Celery instrumentation carries W3C trace context automatically; the explicit
  request ID header supplies log correlation.
- Validate configuration with `docker compose --profile observability config` and the commands in
  CI before debugging application code.
