# Explainable three-way matching

Three-way matching is an explicit API mode. Existing requests remain `TWO_WAY`; clients request
`THREE_WAY` only when receiving evidence is required. The engine compares the extracted invoice,
the selected purchase order and an immutable snapshot of active/reversed goods receipts and prior
matched allocations. It uses `Decimal` arithmetic and never authorizes payment.
The stored policy also includes the deterministic description-assignment threshold and ambiguity
margin inherited from two-way line assignment, so historical decisions remain reproducible.

## Goods receipts

`POST /v1/goods-receipts` accepts a PO ID, external receipt number, timestamp and positive accepted
quantities keyed by PO-line ID. The `(purchase_order_id, external_receipt_number)` business key is
unique. An identical canonical replay returns the existing row; a changed replay returns `409`.
Receipts are immutable. `POST /v1/goods-receipts/{id}/reverse` appends one immutable reversal.
`X-Actor-ID` is required for reversal but is only an unverified development identity boundary,
not production authentication.

## Context, concurrency and allocation

The context fingerprint covers active receipt IDs/quantities/timestamps, reversal IDs, allocations
from other documents, the current document's allocations and the complete `three-way-v1` policy.
Only other-document allocations reduce available quantity, so an invoice never competes with its
own reserved quantity. The context exposes the two allocation groups separately.
A later receipt or reversal can therefore create a new immutable match run without allocating the
same uploaded invoice twice. `GET /v1/matches/{id}/three-way-context` returns the historical snapshot
used for that decision.

PostgreSQL matching, receipt creation and receipt reversal all acquire the same selected-PO row
lock. This serializes receipt-state changes with context construction and the atomic match,
allocation, duplicate-risk and review writes. SQLite ignores `FOR UPDATE`; local SQLite tests
validate lock-protocol participation but do not prove production concurrency serialization.

An allocation is a document-and-PO-level reservation created by the first `MATCHED` run. It retains
the source match and extraction IDs, and its database key is unique across document, PO and invoice
line. Later immutable evaluations reuse an exactly equal PO-line/quantity reservation. A changed
assignment, quantity or line set returns `ALLOCATION_RECONCILIATION_REQUIRED`; the old allocation
is neither moved nor deleted. `NEEDS_REVIEW` creates no allocation, and accepting a review exception
does not retroactively create one. A reversal can invalidate a later evaluation while the original
allocation deliberately continues blocking other invoices until a future explicit adjustment
workflow is implemented.

## Explainable failures

The result uses stable reason codes for no receipt, missing receipt line, reversed receipt,
invoice/cumulative quantity above receipts, receipts above ordered quantity, receipt after invoice,
unit-price mismatch and line-amount mismatch. Every line check includes the PO line, relevant
receipt IDs, ordered/received/prior/available/invoice quantities, tolerance and invoice evidence.

Run the synthetic 25+ scenario evaluation:

```powershell
uv run python scripts/run_three_way_evaluation.py
Get-Content evals/reports/matching/three-way-v1/report.md
```

The report is sequential synthetic engineering evidence, not a production accuracy or concurrency
claim. Its safety invariants are zero false auto-matches and zero allocations on review outcomes.
The Compose suite's simultaneous PostgreSQL requests provide the actual contention test.
