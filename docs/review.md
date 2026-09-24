# Evidence-linked human review

Three-way `MATCH_REASON` triggers share the same case as duplicate-risk `RISK_SIGNAL` triggers.
Case detail embeds matching mode, policy, context URL, receipt-linked checks and risk disposition.
Resolving a case never creates a receipt allocation or authorizes payment.

`NEEDS_REVIEW` match runs open exactly one durable review case. `MATCHED` runs never open a case.
The match run, case, and `CASE_OPENED` event are committed atomically. Historical `NEEDS_REVIEW`
runs can be repaired idempotently with:

```powershell
uv run python scripts/reconcile_review_cases.py
```

## State and concurrency

```text
OPEN --claim--> CLAIMED --resolve--> RESOLVED
                       \--release--> OPEN
```

Comments are allowed on open or claimed cases and advance the case version. Every mutation must
send the current `expected_version`; stale requests return `409` with code `STALE_VERSION` and do
not create an event. Only the assigned reviewer may release or resolve a claimed case. Resolution
requires a nonblank reason and is terminal in this slice.

The API requires `X-Reviewer-ID` on mutations. This header is an **unverified development identity
boundary**, not authentication or authorization suitable for production. Deployments must replace
it with organization-controlled identity and role enforcement.

`ACCEPTED_EXCEPTION` records a reviewer outcome. It does **not** approve or authorize payment.

## Queue and evidence

The queue supports `status`, `assignee`, `reason_code`, `created_before`, `created_after`, opaque
`cursor`, and bounded `limit` filters. Match reason codes are normalized into indexed
`review_case_triggers` rows, so filtering is performed by the database without loading the queue
into application memory. The trigger contract also provides a clean insertion point for future
duplicate and anomaly signals. Case detail embeds the immutable match result, including
reason codes, validation checks, line assignments and extraction evidence coordinates. It also
identifies the exact extraction name and version used by matching.

`RISK_SIGNAL` triggers link to the immutable duplicate-risk assessment that caused routing. A
`MATCHED` result can therefore have an open review case while remaining `MATCHED`. Review responses
expose both normalized trigger types, while `reason_codes` remains for backward compatibility.

Endpoints:

```text
GET  /v1/review-cases
GET  /v1/review-cases/{case_id}
POST /v1/review-cases/{case_id}/claim
POST /v1/review-cases/{case_id}/release
POST /v1/review-cases/{case_id}/comments
POST /v1/review-cases/{case_id}/resolve
GET  /v1/review-cases/{case_id}/events
GET  /v1/review-cases/{case_id}/audit-verification
```

## Tamper evidence

Events are append-only through application code. New events use `review-audit-v2`, which hashes the
UTF-8 encoding of one canonical, sorted JSON envelope containing `hash_version`, case ID, sequence,
event type, actor, canonical UTC timestamp, payload and previous hash. Explicit field names and JSON
boundaries avoid ambiguity between adjacent components. Events created before this migration are
marked `review-audit-v1`; verification dispatches to the stored version so their original hashes
remain valid. The verification endpoint recomputes the chain, validates event ordering and
transitions, reconstructs state and the original opening trigger snapshot, and compares state with
the materialized case. It never recomputes historical risk with current policy defaults.

This is application-level tamper evidence. It can detect ordinary mutation or sequence corruption;
it cannot prevent a database administrator from consistently rewriting both history and hashes.
Production assurance would additionally require restricted database roles and externally anchored
or signed audit records.

## Example

```powershell
$headers = @{ "X-Reviewer-ID" = "developer-reviewer" }
$queue = Invoke-RestMethod http://localhost:8000/v1/review-cases?status=OPEN
$case = $queue.items[0]

$claimed = Invoke-RestMethod -Method Post -Headers $headers `
  -ContentType application/json `
  -Uri "http://localhost:8000/v1/review-cases/$($case.id)/claim" `
  -Body (@{ expected_version = $case.version } | ConvertTo-Json)

$resolved = Invoke-RestMethod -Method Post -Headers $headers `
  -ContentType application/json `
  -Uri "http://localhost:8000/v1/review-cases/$($case.id)/resolve" `
  -Body (@{
    expected_version = $claimed.version
    resolution = "CORRECTION_REQUESTED"
    reason = "Invoice currency must match the purchase order."
  } | ConvertTo-Json)
```

Run the 17-scenario synthetic safety evaluation with:

```powershell
uv run python scripts/run_review_evaluation.py
Get-Content evals/reports/review/review-v1/report.md
```
