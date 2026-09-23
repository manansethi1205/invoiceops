# InvoiceOps

InvoiceOps is an evidence-first accounts-payable automation project. AI will handle document
perception and ambiguity; deterministic code will perform arithmetic, apply policy, and authorize
decisions. Only synthetic or de-identified financial documents belong in this repository.

## Measured results at a glance

| Evaluation | Scope | Key measured result |
| --- | --- | --- |
| Deterministic extraction 0.2.0 | 15-document synthetic holdout in Docker | 100% header overall exact, 100% exact line-item F1, 0 failures |
| Hybrid replay 0.3.0 | 12 synthetic stress documents, no network | 93.06% header coverage, 100% line-item F1, all grounded conflicts abstained |
| Two-way matching v1 | 18 synthetic business scenarios | 100% expected-decision accuracy, 0 false auto-matches |
| Review workflow v1 | 17 synthetic state/concurrency scenarios | 100% category accuracy, 0 false automatic resolutions |
| DocILE external context | Fixed 100-document validation sample | supported LIR F1 18.49% end-to-end / 22.28% precomputed OCR; supported KILE F1 0% |

Synthetic results are project measurements, not production claims. DocILE results are reported
separately as an external stress benchmark and expose the deterministic baseline's generalization
limits.

```text
upload -> extraction + evidence -> deterministic PO matching
                                      | MATCHED
                                      ` NEEDS_REVIEW -> OPEN -> CLAIMED -> RESOLVED
                                                               `-> OPEN (release)
                                                    -> hash-chained audit reconstruction
```

## Implemented vertical slice

`POST /v1/invoices` accepts one PDF, JPEG, or PNG (15 MiB by default), stores it in S3-compatible
object storage, creates a durable queued job in PostgreSQL, dispatches it through Celery/Redis, and
returns `202 Accepted` with job, document, status, and extraction URLs. `GET /v1/jobs/{job_id}`
returns the job state. `GET /v1/invoices/{document_id}/extraction` returns the current versioned
extraction state and, when complete, the typed invoice with source evidence.

The worker downloads the stored document, performs text/OCR preprocessing and deterministic header
extraction, and persists one result per document, extractor name, and extractor version. Celery
redelivery reuses a completed extraction instead of repeating it.

An optional deterministic-first vision fallback is implemented as `hybrid-routed@0.3.0` while the
frozen `deterministic-baseline@0.2.0` remains intact. The router invokes a provider only for typed
quality failures. Strict model candidates are accepted only when their quotes map uniquely to real
embedded-text/OCR tokens. Grounded conflicts become `AMBIGUOUS`; provider failure preserves the
deterministic invoice. The VLM is disabled and model-less by default, and confidence never
authorizes matching, approval, or payment.

The deterministic two-way matching slice accepts typed purchase orders, validates invoice
arithmetic, and compares an explicitly selected PO with a successful extraction. Matching is
synchronous and returns only `MATCHED` or `NEEDS_REVIEW`, with versioned tolerances, reason codes,
line assignments, and invoice evidence. Ambiguous, incomplete, or inconsistent observations can
never produce `MATCHED`; no model makes arithmetic or approval decisions.

Every `NEEDS_REVIEW` result now opens exactly one evidence-linked case and opening audit event in
the same transaction as the immutable match run. Reviewers can claim, comment, release and resolve
with optimistic concurrency and ownership checks. Events form an application-level SHA-256 chain
that can reconstruct materialized state. `X-Reviewer-ID` is explicitly an unverified development
identity boundary, and `ACCEPTED_EXCEPTION` never authorizes payment.

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
uv run pytest -m "not docker and not docile"
uv run ruff check .
uv run mypy apps invoiceops workers
```

Run marker-specific suites explicitly when their required environment is available:

```powershell
uv run pytest -m docile
uv run pytest -m docker
```

Private DocILE tests require `DOCILE_DATASET_PATH`. Docker tests are normally run through the
Compose command below, which supplies the real service dependencies and `API_BASE_URL`.

Run the real PostgreSQL/Redis/MinIO/worker black-box tests in Compose:

```powershell
docker compose --profile test up --build --abort-on-container-exit --exit-code-from integration-tests integration-tests
docker compose --profile hybrid-test up --build --abort-on-container-exit --exit-code-from integration-tests-hybrid integration-tests-hybrid
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

Run the deterministic business-scenario evaluation:

```powershell
uv run python scripts/run_matching_evaluation.py
Get-Content evals/reports/matching/matching-v1/report.md
```

The 18 scenarios are synthetic. Their aggregate result is engineering evidence, not a production
accuracy claim. The safety invariant is `false_auto_match_count == 0`.

Run the network-free hybrid replay evaluation:

```powershell
uv run python scripts/run_hybrid_evaluation.py --mode hybrid-replay
Get-Content evals/reports/hybrid/0.3.0-replay/report.md
```

Live mode is guarded and requires explicit manifest wiring, `--allow-live`, an enabled provider,
an explicitly selected model, and credentials. Ordinary tests and CI make no live provider calls.

Run the synthetic review-workflow evaluation:

```powershell
uv run python scripts/run_review_evaluation.py
Get-Content evals/reports/review/review-v1/report.md
```

It covers allowed and invalid transitions, stale versions, ownership, repeated requests and the
false-automatic-resolution safety invariant.

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
`DOCILE_DATASET_PATH`:

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  scripts/run_docile_evaluation.py --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/smoke.json `
  --output-dir evals/reports/docile/0.2.0-smoke
```

See the [evaluation guide](docs/evaluation.md#docile-external-benchmark) for dataset placement and
the fixed 100-document command.

## API example

```powershell
curl.exe -F "file=@synthetic-invoice.pdf;type=application/pdf" http://localhost:8000/v1/invoices
curl.exe http://localhost:8000/v1/jobs/JOB_ID
```

Purchase-order creation and matching examples, including both `MATCHED` and `NEEDS_REVIEW`, are in
[the two-way matching guide](docs/matching.md#api-demonstration).

## Product evidence

Initial discovery with a finance practitioner identified quantity, unit rate, counterparty, and
GST rate as frequent manual-entry fields. Escalation is driven by approval thresholds, mismatches,
disputes, and exceptional circumstances. Tolerances must be policy- and agreement-specific rather
than model-decided. Approvers may require a PO, order confirmation, advance evidence, and email
approval. These findings are product inputs, not measured system results.

See [architecture](docs/architecture.md) and [ADR-001](docs/adr/001-ingestion-boundary.md).
See [hybrid extraction](docs/hybrid-extraction.md) for routing, grounding, fusion, and privacy.
See [two-way matching](docs/matching.md) for policy definitions, reason codes, API behavior, and
known limitations.
See [human review](docs/review.md) for state transitions, concurrency, identity limitations,
evidence navigation, reconciliation and audit verification.
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
