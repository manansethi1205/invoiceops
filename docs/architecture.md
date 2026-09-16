# Architecture

The upload path is deliberately small and durable:

```text
client -> FastAPI -> object storage
                  -> PostgreSQL job row -> Redis/Celery -> extraction worker
client <- 202 + job ID
client -> GET job status -> PostgreSQL
```

The database stores metadata and workflow state; original bytes stay in object storage. Every
document receives a content digest for future duplicate detection. The object is written before
the row is committed, and removed if that commit fails. If dispatch fails, the queued row remains
durable so a reconciliation process can safely redispatch it.

Later slices add preprocessing, OCR, schema-constrained extraction with evidence coordinates,
deterministic validation/matching, anomaly scoring, review, audit events, and evaluation lineage.

