# Implementation guide: durable invoice ingestion slice

This guide explains how the current repository was assembled and why each part exists. Follow the
order below when recreating the slice. The resulting request path is:

```text
POST invoice -> validate bytes -> write object -> commit document/job -> enqueue UUID -> HTTP 202
worker receives UUID -> processing -> succeeded
GET job UUID -> read durable database state -> JSON response
```

## 1. Create the Python project

Create `pyproject.toml` for Python 3.12 with these runtime concerns:

- FastAPI, Uvicorn, and `python-multipart` for the HTTP upload API.
- Pydantic Settings for environment configuration.
- SQLAlchemy, psycopg, and Alembic for PostgreSQL persistence and migrations.
- boto3 for S3/MinIO object storage.
- Celery with Redis support for asynchronous dispatch.
- pytest, HTTPX, Ruff, and mypy as development dependencies.

Use Hatchling only as the package build backend and package `apps`, `invoiceops`, and `workers`.
Commit `uv.lock`, set `.python-version` to `3.12`, then install with `uv sync`.

## 2. Define configuration

Implement `invoiceops/config.py` with a Pydantic `Settings` class. It must contain the database
URL, Redis URL, S3 endpoint/credentials/bucket/region, optional server-side encryption, and maximum
upload size. Cache `get_settings()` so clients and engines are not rebuilt on every request.

Keep local values in `.env.example`; copy it to ignored `.env` at runtime. Never commit deployed
credentials.

## 3. Define durable database state

Implement `invoiceops/db.py` with:

- one SQLAlchemy declarative `Base`;
- an engine built from settings with connection health checks;
- `SessionLocal` with `expire_on_commit=False`;
- a FastAPI session dependency that always closes the session.

Implement `invoiceops/models.py` with two tables:

- `Document`: UUID, sanitized original filename, MIME type, size, SHA-256, unique object key, and
  creation time;
- `IngestionJob`: UUID, one-to-one document foreign key, explicit status enum, safe error fields,
  and timestamps.

The SHA-256 is evidence for later duplicate detection, but the current slice does not reject a
duplicate because duplicate policy is not yet defined.

## 4. Add the migration

Configure Alembic through `alembic.ini` and `infrastructure/migrations/env.py`. Import the models so
Alembic sees the metadata and obtain the database URL from the same settings object as the app.

Create `infrastructure/migrations/versions/20260915_0001_ingestion.py` with both tables, indexes,
foreign-key deletion behavior, and a reversible downgrade. Compose runs `alembic upgrade head` as
a one-shot service before the API and worker start.

## 5. Put storage and queue behind interfaces

In `invoiceops/ingestion/storage.py`, define an `ObjectStore` protocol with `put` and `delete`.
Implement `S3ObjectStore` with boto3. Its endpoint remains configurable so the same application
works with local MinIO and AWS S3. Enable server-side encryption only when the target storage is
configured for it.

In `invoiceops/ingestion/dispatch.py`, define a `JobDispatcher` protocol and a Celery implementation
that sends only the job UUID. Never put document bytes on Redis.

These protocols let tests use memory fakes with no Docker or cloud services.

## 6. Implement the ingestion transaction boundary

Implement `invoiceops/ingestion/service.py` as framework-independent application logic:

1. Allow only PDF, JPEG, and PNG MIME types.
2. Reject empty and oversized bodies.
3. Verify that magic bytes match the declared MIME type.
4. Sanitize the filename to its final path component.
5. Generate a document UUID and object key.
6. Calculate SHA-256.
7. Write the object.
8. Add the document and queued job, then commit.
9. Delete the object and roll back if the database commit fails.
10. Dispatch the committed job UUID.

If queue dispatch fails, leave the durable row queued. A later production slice should add a
transactional outbox or a reconciliation task to redispatch queued rows. Do not delete an accepted
invoice merely because Redis is briefly unavailable.

## 7. Expose the API contract

Define response schemas in `invoiceops/schemas/jobs.py`. Keep storage keys and credentials out of
public responses.

Implement `apps/api/main.py`:

- `GET /healthz` returns a shallow process health response;
- `POST /v1/invoices` performs a bounded read of `max_upload_bytes + 1`, invokes the service,
  maps known validation failures to 400/413/415, and returns 202 with job ID and status URL;
- `GET /v1/jobs/{job_id}` validates the UUID, returns the database representation, and produces
  404 for an unknown job.

Create dependency factories in `apps/api/dependencies.py` so tests can replace S3 and Celery.

## 8. Implement the worker boundary

Configure Celery in `workers/extraction/celery_app.py` with Redis as broker/backend, late
acknowledgement, rejection on worker loss, prefetch of one, and explicit task-module inclusion.

Implement the idempotent task in `workers/extraction/tasks.py`. Load by UUID, ignore missing or
already-successful work, mark it processing, and then succeeded. The current task deliberately does
not claim to perform OCR; preprocessing and extraction are the next vertical slice.

## 9. Package local infrastructure

Build one Python 3.12 image using `infrastructure/docker/Dockerfile` and the locked dependencies.
Use `.dockerignore` to exclude the Windows `.venv`, `.env`, caches, data, and work directories.

Define these Compose services:

- `postgres`: metadata and job source of truth;
- `redis`: Celery broker/backend;
- `minio`: local S3-compatible storage;
- `minio-init`: idempotently creates the bucket;
- `migrate`: upgrades the schema and exits successfully;
- `api`: starts only after migration, Redis, and bucket initialization;
- `worker`: starts with the same dependencies.

Do not bind-mount the Windows repository onto `/app`: that hides the Linux `.venv` in the image.
Rebuild after code changes.

MinIO community binaries are pinned from Quay for reproducible local development. This is a
legacy, loopback-bound synthetic-data dependency. A deployed environment uses managed S3 and must
not inherit the local credentials or image choice.

## 10. Test without external services

In `tests/conftest.py`, build an in-memory SQLite database with `StaticPool`, an in-memory object
store, and a dispatcher that records UUIDs. Override the FastAPI dependencies for every test and
clear overrides afterwards.

In `tests/integration/test_ingestion_api.py`, prove:

- a valid PDF is stored, dispatched, and queryable;
- unsupported MIME types are rejected;
- declared type and magic-byte mismatches are rejected;
- empty files are rejected;
- oversized files are rejected;
- unknown jobs return 404.

Run the isolated suite and static gates before every Compose smoke test:

```powershell
uv run pytest -q -p no:cacheprovider
uv run ruff check .
uv run mypy apps invoiceops workers
```

Then follow `docs/local-runbook.md` to prove the real PostgreSQL, Redis, MinIO, migration, API, and
worker integration from end to end.

## Definition of done for this slice

- Invalid uploads fail with a specific client error.
- A valid upload exists in object storage and has matching database metadata.
- The API returns 202 and a usable status URL.
- The queue carries only a UUID.
- The worker changes durable state to succeeded.
- Status polling returns the state from PostgreSQL.
- Six isolated tests plus Ruff and strict mypy pass.
- The full Compose smoke test passes with Docker Desktop running.
- Only synthetic or de-identified documents are used.
