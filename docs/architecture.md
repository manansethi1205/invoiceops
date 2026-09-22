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

The optional perception path is deterministic-first:

```text
stored document -> deterministic-baseline@0.2.0 (persisted)
                -> pure quality router
                    -> sufficient: hybrid-routed@0.3.0 copies canonical baseline
                    -> insufficient: bounded render -> strict VLM candidate
                                     -> quote-to-token grounding
                                     -> conservative deterministic fusion
                -> separate ExtractionRun + sanitized ModelCall lineage
                -> existing deterministic validation and PO matching
```

Provider construction is lazy. Images and document text are never logged, model boxes are ignored,
and document instructions are untrusted data. Request fingerprints make attempt persistence
idempotent. External exactly-once execution is not claimed: a crash between provider response and
database commit can cause an at-least-once retry, while a persisted success is reused. Read and
matching paths prefer successful 0.3.0, fall back to 0.2.0, and never rewrite historical matches.
