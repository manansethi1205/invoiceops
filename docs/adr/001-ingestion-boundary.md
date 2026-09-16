# ADR-001: Durable ingestion boundary

- Status: accepted
- Date: 2026-09-15

## Decision

Store document bytes in S3-compatible object storage, metadata and job state in PostgreSQL, and
dispatch only the job identifier through Celery/Redis. Return HTTP 202 after durable persistence.

## Consequences

Workers never receive large financial documents through the broker. A queued database row is the
source of truth when dispatch is interrupted. The small gap between database commit and broker
dispatch requires an idempotent reconciliation task in a later operational slice; production
deployment should replace this gap with an outbox pattern.

