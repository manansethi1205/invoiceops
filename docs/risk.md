# Deterministic duplicate-invoice risk

## Business purpose

SHA-256 ingestion idempotency prevents identical bytes from creating duplicate work. It cannot
recognize the same business invoice after re-export, rescan, recompression, rename or layout change.
The duplicate-risk layer compares stable business features after extraction and matching. It is
deterministic, versioned and explainable; it neither rejects an invoice nor authorizes payment.

```text
matching result != risk disposition != human resolution != payment authorization
```

## Features and normalization

The stored feature snapshot contains normalized vendor and invoice number, invoice date, currency,
decimal total, purchase-order ID, document ID, extraction-run ID and match-run ID. The explicitly
selected purchase order supplies vendor identity in this slice.

Vendor normalization applies Unicode NFKC, case folding, punctuation-to-space normalization and
whitespace collapse while preserving letters and digits. Invoice-number normalization applies NFKC
and case folding, then removes formatting separators while preserving every letter, digit and
leading zero. No LLM, embeddings, float-based money calculation or numeric identifier parsing is
used.

## Versioned policy

`duplicate-risk-v1` stores its complete effective snapshot with every assessment:

```yaml
amount_absolute_tolerance: "0.02"
date_window_days: 7
invoice_number_similarity_threshold: "0.92"
route_incomplete_to_review: true
```

The similarity threshold is a ratio: `0.92` means 92% similarity. Financial tolerance rejects
float input and is evaluated with `Decimal`.

## Signals

- `EXACT_BUSINESS_KEY_DUPLICATE`: vendor, invoice number, date and currency match, with total inside
  the absolute tolerance.
- `REUSED_VENDOR_INVOICE_NUMBER`: vendor and invoice number match but another material key differs.
- `SAME_PO_INVOICE_REPLAY`: the same normalized invoice number was processed against the same PO.
- `NEAR_DUPLICATE`: vendor and currency match, amount/date are inside policy boundaries, and invoice
  number similarity meets the threshold. Cross-vendor similarity is never flagged.
- `DUPLICATE_CHECK_INCOMPLETE`: one or more required features are unavailable or ambiguous.

Signals contain compared historical match IDs, observed/reference features and stable explanations.
There is deliberately no opaque aggregate risk score.

Any duplicate signal produces `NEEDS_REVIEW`. Incomplete data produces `NEEDS_REVIEW` when policy
enables routing and `NOT_ASSESSABLE` otherwise. Complete input with no signal is `CLEAR`. None of
these dispositions reject a document or approve payment.

## Persistence and review routing

Every match has at most one assessment per policy version. A new match, its assessment/signals,
review case, normalized triggers and opening audit event commit in one transaction. Database
uniqueness is the final retry/concurrency safeguard. `MATCHED` plus duplicate risk opens a case
without changing the immutable match decision.

Review triggers use `MATCH_REASON` or `RISK_SIGNAL` and can be filtered in SQL. The `CASE_OPENED` v2
audit payload stores the exact opening trigger snapshot; verification reconstructs that snapshot
without rerunning old invoices under current defaults.

Historical repair is idempotent:

```powershell
uv run python scripts/reconcile_duplicate_risk.py
```

## API

```http
GET /v1/matches/{match_run_id}/risk
GET /v1/risk-assessments/{risk_assessment_id}
GET /v1/review-cases?trigger_type=RISK_SIGNAL&trigger_code=NEAR_DUPLICATE
```

Risk responses include policy/feature snapshots, completeness, ordered signals, compared match IDs
and an optional review-case ID. There is no mutation endpoint for assessments or signals.

## Evaluation and limitations

```powershell
uv run python scripts/run_duplicate_risk_evaluation.py `
  --output-dir evals/reports/risk/duplicate-risk-v1
```

The evaluation contains at least 25 deterministic synthetic/de-identified scenarios. The required
safety invariant is `known_duplicate_false_clear_count == 0`. These measurements are not production
fraud-detection claims. This slice does not detect bank-detail changes, coordinated fraud, semantic
vendor aliases, credit-note relationships or generic anomalies.
