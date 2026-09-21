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

The current deterministic decision path is:

```text
successful versioned extraction + explicitly selected purchase order
        -> financial validation
        -> exact/fuzzy deterministic one-to-one line assignment
        -> quantity, price, currency and line-amount checks
        -> MATCHED or NEEDS_REVIEW
        -> immutable policy snapshot + reason codes + invoice provenance
```

Extraction supplies observations and evidence. Matching code alone performs arithmetic and applies
the versioned policy. Match runs reference the exact extraction row and are idempotent across
retries. Later slices add anomaly scoring, review workflow, audit events, and evaluation lineage.
