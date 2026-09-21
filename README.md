# InvoiceOps

InvoiceOps is an evidence-first accounts-payable automation project. AI will handle document
perception and ambiguity; deterministic code will perform arithmetic, apply policy, and authorize
decisions. Only synthetic or de-identified financial documents belong in this repository.

## Implemented vertical slice

`POST /v1/invoices` accepts one PDF, JPEG, or PNG (15 MiB by default), stores it in S3-compatible
object storage, creates a durable queued job in PostgreSQL, dispatches it through Celery/Redis, and
returns `202 Accepted` with job, document, status, and extraction URLs. `GET /v1/jobs/{job_id}`
returns the job state. `GET /v1/invoices/{document_id}/extraction` returns the current versioned
extraction state and, when complete, the typed invoice with source evidence.

The worker downloads the stored document, performs text/OCR preprocessing and deterministic header
extraction, and persists one result per document, extractor name, and extractor version. Celery
redelivery reuses a completed extraction instead of repeating it.

Uploads are idempotent by SHA-256: repeated bytes reuse the existing document and job, including
under concurrent requests through a unique database index. API and worker application events are
JSON structured logs. Celery uses late acknowledgement, safe redelivery, bounded exponential
retry, and a terminal failed state.

## Run locally

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The API docs are at `http://localhost:8000/docs` and the MinIO console is at
`http://localhost:9001`. Docker Compose runs Alembic migrations before starting the API or worker.

Run local quality checks:

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy apps invoiceops workers
```

Run the real PostgreSQL/Redis/MinIO/worker black-box tests in Compose:

```powershell
docker compose --profile test up --build --abort-on-container-exit --exit-code-from integration-tests integration-tests
docker compose down
```

Run the reproducible synthetic evaluation corpus:

```powershell
uv run python scripts/generate_synthetic_evaluation.py
uv run python -m invoiceops.evaluation --manifest evals/manifests/dev.jsonl --output-dir evals/reports/development
uv run python -m invoiceops.evaluation --manifest evals/manifests/holdout.jsonl --output-dir evals/reports/holdout/0.2.0 --allow-holdout
```

The holdout flag is mandatory. Reports contain normalized predictions and aggregate metrics, not
raw page text or evidence snippets. Metric definitions and denominator policies are documented in
[the evaluation guide](docs/evaluation.md).

OCR-bearing manifests require Tesseract before any document bytes are processed. Run the frozen
holdout in the reproducible evaluation container:

```powershell
docker compose --profile evaluation run --rm evaluator `
  --manifest evals/manifests/holdout.jsonl `
  --output-dir evals/reports/synthetic/0.2.0-container `
  --allow-holdout
```

DocILE tooling is isolated in the `evaluation` dependency group. External documents, OCR and raw
predictions are ignored; only ID-only manifests and aggregate reports may be committed. See the
[DocILE field mapping](docs/docile-field-mapping.md).

Run the two-mode DocILE smoke benchmark in the Tesseract-enabled evaluation container after setting
`DOCILE_DATASET_PATH`; see the [evaluation guide](docs/evaluation.md#docile-external-benchmark).

## API example

```powershell
curl.exe -F "file=@synthetic-invoice.pdf;type=application/pdf" http://localhost:8000/v1/invoices
curl.exe http://localhost:8000/v1/jobs/JOB_ID
```

## Product evidence

Initial discovery with a finance practitioner identified quantity, unit rate, counterparty, and
GST rate as frequent manual-entry fields. Escalation is driven by approval thresholds, mismatches,
disputes, and exceptional circumstances. Tolerances must be policy- and agreement-specific rather
than model-decided. Approvers may require a PO, order confirmation, advance evidence, and email
approval. These findings are product inputs, not measured system results.

See [architecture](docs/architecture.md) and [ADR-001](docs/adr/001-ingestion-boundary.md).
The delivery sequence is captured in [the roadmap](docs/roadmap.md).
The current slice is explained file-by-file in the
[implementation guide](docs/implementation-guide.md).
For exact Windows setup, smoke-test, troubleshooting, and cleanup commands, use the
[local runbook](docs/local-runbook.md).

## Deterministic extraction assumptions

Header extraction is rule-based and retains source coordinates for every selected value. Numeric
invoice dates use Indian day-first ordering (`DD/MM/YYYY` or `DD-MM-YYYY`); ISO dates use
`YYYY-MM-DD`. Ambiguous top-ranked values are returned as ambiguous instead of being guessed.
Money is parsed with `Decimal`, and the `$` symbol is not automatically treated as USD.

Line-item extraction detects positioned table headers and assigns words to inferred normalized
column ranges. Missing financial cells remain missing rather than being calculated. Wrapped
descriptions are joined only within the same detected table section and page; cross-page
description continuation is intentionally unsupported in the deterministic baseline.
