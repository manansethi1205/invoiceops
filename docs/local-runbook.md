# Local implementation and test runbook (Windows PowerShell)

For a three-way smoke test, create a PO, post its immutable receipt to
`POST /v1/goods-receipts`, then match with `"mode":"THREE_WAY"`. Corrections use
`POST /v1/goods-receipts/{receipt_id}/reverse` with development-only `X-Actor-ID`.

These instructions run the ingestion slice implemented today: upload document, store object,
create and dispatch a job, return its identifier, and poll its status.

## If the stack is already running

If Docker Desktop shows the `i-w` project and `docker compose logs api worker` shows the API
running, Redis connected, `invoiceops.process_document` registered, and the worker ready, the stack
is healthy. Rebuild once after the latest repository changes so the worker runs as a non-root user
and health checks no longer flood access logs:

```powershell
Set-Location "<path-to-your-clone>"
docker compose down
docker compose up --build -d
docker compose ps -a
docker compose logs --tail=40 api worker
```

Continue at section 6 for a manual smoke test, or section 13 for automated Compose tests.

## 1. Prerequisites

Install the following once:

- Python 3.12
- `uv`
- Docker Desktop for Windows using Linux containers/WSL 2

Open a new PowerShell window and move into the repository:

```powershell
Set-Location "<path-to-your-clone>"
python --version
uv --version
docker --version
```

Python should report `3.12.x`. The Docker client version is not enough by itself; the engine must
also be running.

## 2. Start Docker Desktop and verify the engine

The error `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`
means Docker Desktop's Linux engine is not running. Start Docker Desktop from the Windows Start
menu, wait until it reports that the engine is running, then execute:

```powershell
docker context use desktop-linux
docker info
```

`docker info` must print both a Client and Server section. If it still reports the named-pipe
error, quit Docker Desktop completely, reopen it, wait for startup, and rerun `docker info`.

If Docker Desktop reports a WSL problem, inspect it with:

```powershell
wsl --status
wsl --update
```

Restart Windows if `wsl --update` requests it. Do not continue to Compose until `docker info`
succeeds.

## 3. Install Python dependencies and configure local services

Run each complete command; `Copy-Item` by itself is incomplete.

```powershell
uv sync
Copy-Item .env.example .env -Force
```

The checked-in example contains local-only credentials. Never reuse them in a deployed system.

## 4. Run the fast feedback checks

```powershell
uv run pytest -m "not docker and not docile" -q -p no:cacheprovider
uv run ruff check .
uv run mypy apps invoiceops workers
```

All non-Docker tests should pass, followed by `All checks passed!` and
`Success: no issues found`.
`-p no:cacheprovider` avoids the non-fatal `.pytest_cache` access warning seen on this machine.

## 5. Build and start the full stack

The Compose file uses pinned `quay.io/minio/...` images. The former `minio/minio:latest` and
`minio/mc:latest` Docker Hub coordinates are no longer used. The pinned community server is a
legacy binary intended only for this loopback-bound, synthetic-data development environment - not
for deployment or real financial documents.

```powershell
docker compose config --quiet
docker compose pull
docker compose up --build -d
docker compose ps -a
```

Expected services:

- `postgres`, `redis`, `minio`, `api`, and `worker` are running.
- `migrate` and `minio-init` have exited with code 0; these are successful one-shot services.

Confirm startup and migrations:

```powershell
docker compose logs migrate
docker compose logs minio-init
docker compose logs api
docker compose logs worker
```

The migration log should show upgrades through `20260924_0008`. The worker log should list
`invoiceops.process_document` as a registered task.

Repair historical matches that predate duplicate-risk persistence, then inspect aggregate counts:

```powershell
uv run python scripts/reconcile_duplicate_risk.py
```

The command is idempotent: a second run reports existing assessments as reused and creates no
duplicate review cases or triggers.

The worker should report concurrency `2` and should not display the Celery superuser warning. A
small amount of plain Celery/Uvicorn lifecycle output is normal; InvoiceOps application and request
events are JSON.

## 6. Verify the API

```powershell
Invoke-RestMethod http://localhost:8000/healthz
Start-Process http://localhost:8000/docs
```

The health response should contain `status = ok`. Swagger UI should show the invoice/job/extraction
routes plus purchase-order, matching and review-workflow routes.

## 7. Create safe synthetic test data

The earlier curl command failed because `synthetic-invoice.pdf` did not exist. Generate it:

```powershell
uv run python scripts/create_synthetic_invoice.py
Test-Path .\synthetic-invoice.pdf
```

`Test-Path` must return `True`. This file contains only demonstration data. Each generator run uses
a new synthetic invoice number, so generate once and upload that same file twice for the
idempotency check.

## 8. Upload and poll the job

PowerShell-native test (PowerShell 7 or later):

```powershell
$upload = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/invoices `
  -Form @{ file = Get-Item .\synthetic-invoice.pdf }

$upload | Format-List
$job = Invoke-RestMethod -Uri $upload.status_url
$job | Format-List
```

The upload should return `job_id`, `document_id`, `status = queued`, `status_url`,
`extraction_url`, and `deduplicated = False`. Poll `status_url` until the job succeeds, then request
`extraction_url` to inspect the typed invoice and evidence.

Upload the same bytes again to prove idempotency:

```powershell
$duplicate = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/v1/invoices `
  -Form @{ file = Get-Item .\synthetic-invoice.pdf }

$duplicate | Format-List
$duplicate.job_id -eq $upload.job_id
```

The second response must contain `deduplicated = True`, and the comparison must return `True`.

Equivalent curl commands:

```powershell
curl.exe -F "file=@synthetic-invoice.pdf;type=application/pdf" http://localhost:8000/v1/invoices
curl.exe http://localhost:8000/v1/jobs/REPLACE_WITH_JOB_ID
```

Do not type the literal placeholder `REPLACE_WITH_JOB_ID`; paste the returned UUID.

## 9. Verify persistence and asynchronous processing

Inspect the database rows:

```powershell
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT id, original_filename, byte_size, sha256, object_key, created_at FROM documents;"
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT id, document_id, status, error_code, created_at, updated_at FROM ingestion_jobs;"
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT id, document_id, extractor_name, extractor_version, schema_version, status, used_ocr, latency_ms, error_code FROM extraction_runs;"
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT extraction_run_id, provider, requested_model, prompt_version, status, routing_json, input_tokens, output_tokens, latency_ms, error_code FROM model_calls;"
```

Open `http://localhost:9001`, sign in with `invoiceops` and
`change-me-in-real-deployments`, open the `invoice-documents` bucket, and verify the object exists
under `invoices/<document-id>/synthetic-invoice.pdf`.

Inspect the worker transition:

```powershell
docker compose logs --since=5m worker
```

Confirm that no checksum has more than one document and inspect the uploaded job:

```powershell
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT sha256, COUNT(*) FROM documents GROUP BY sha256 HAVING COUNT(*) > 1;"
docker compose exec postgres psql -U invoiceops -d invoiceops -c "SELECT j.id, j.status, d.sha256, d.object_key FROM ingestion_jobs j JOIN documents d ON d.id = j.document_id ORDER BY j.created_at DESC LIMIT 5;"
```

The duplicate query must return zero rows. The recent-jobs query should show the uploaded job once.

## 10. Exercise rejection paths

Unsupported content type:

```powershell
Set-Content .\not-an-invoice.txt "not an invoice"
curl.exe -i -F "file=@not-an-invoice.txt;type=text/plain" http://localhost:8000/v1/invoices
```

Expect HTTP `415`.

Missing job:

```powershell
curl.exe -i http://localhost:8000/v1/jobs/00000000-0000-0000-0000-000000000000
```

Expect HTTP `404`.

## 11. Stop or reset the stack

Stop containers while keeping PostgreSQL and MinIO data:

```powershell
docker compose down
```

Run the fake-provider path without network access or credentials. It proves both lazy provider
initialization for a complete invoice and safe deterministic fallback for an incomplete invoice:

```powershell
docker compose --profile hybrid-test up --build --abort-on-container-exit `
  --exit-code-from integration-tests-hybrid integration-tests-hybrid
docker compose down
```

To configure a real provider, set `VLM_ENABLED=true`, `VLM_PROVIDER=openai`, an explicitly chosen
`VLM_MODEL`, and `OPENAI_API_KEY` in an untracked environment file. Never commit or log the key.
Provider failure records only a safe code and retains the deterministic result.

If the normal stack is already running, Compose will reuse or recreate its services as required.
For the clearest output, stop it first with `docker compose down`, run the integration command, and
then restart it with `docker compose up --build -d`.

For a deliberate clean reset of this project's local Docker data only:

```powershell
docker compose down --volumes
```

The second command permanently removes this Compose project's PostgreSQL and MinIO volumes. The
synthetic PDF in the repository is unaffected and can be deleted normally when no longer needed.

## 12. Development loop

The reliable loop after editing code is:

```powershell
uv run pytest -m "not docker and not docile" -q -p no:cacheprovider
uv run ruff check .
uv run mypy apps invoiceops workers
docker compose up --build -d
docker compose logs --tail=100 api worker
```

The containers intentionally do not bind-mount the Windows virtual environment. Rebuilding after
code changes prevents a Windows `.venv` from hiding the Linux environment inside the image.

## 13. Run black-box integration tests in Docker Compose

This command builds a test image with development dependencies, starts PostgreSQL, Redis, MinIO,
migrations, the API, and the worker, then tests duplicate upload reuse, terminal job status, and a
clear invalid-file response:

```powershell
docker compose --profile test up --build --abort-on-container-exit --exit-code-from integration-tests integration-tests
```

The command must exit with code 0 and report two passing Docker tests. Inspect structured
application events with:

```powershell
docker compose logs api worker
```

Each InvoiceOps application event is one JSON object containing fields such as `timestamp`,
`level`, `event`, `job_id`, `document_id`, `status`, and `retry_count`. Celery's own lifecycle
messages may use Celery's standard format.

Stop the supporting services after the test:

```powershell
docker compose down
```

If you want the normal application running again after the test:

```powershell
docker compose up --build -d
docker compose ps -a
```

## 14. Operate and verify the review workflow

After creating a deliberately mismatched purchase order and matching it, inspect the queue at
`http://localhost:8000/docs` or follow the PowerShell example in [the review guide](review.md).
Mutations require `X-Reviewer-ID`; it is an unverified local-development identity only.

Verify all case histories after an upgrade:

```powershell
uv run python scripts/reconcile_review_cases.py
uv run python scripts/run_review_evaluation.py
Get-Content evals/reports/review/review-v1/report.md
```

Reconciliation is safe to repeat. It creates only missing cases for historical `NEEDS_REVIEW`
runs and prints aggregate counts. Use the per-case `audit-verification` endpoint to recompute the
hash chain and compare reconstructed state with the materialized case.
