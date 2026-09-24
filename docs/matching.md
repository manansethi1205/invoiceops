# Deterministic financial validation and two-way PO matching

This document covers `TWO_WAY`, the backward-compatible default. Explicit goods-receipt matching
is documented in [three-way-matching.md](three-way-matching.md).

This slice compares a successfully extracted invoice with a purchase order explicitly selected by
the caller. This page describes two-way matching only; automatic PO discovery, ERP integration,
approval routing, and three-way matching are intentionally deferred.

`external_po_number` is indexed but intentionally not globally unique. Real PO identity requires
tenant/company scope; that scope is not implemented yet, so callers select the database PO UUID
explicitly and must not treat the external number as a global identifier.

## Decision boundary

Document extraction supplies typed observations and source evidence. Deterministic code performs
all arithmetic, tolerance checks, line assignment, and final classification. Description
similarity proposes a one-to-one assignment; it never authorizes payment or resolves ambiguity.

The only decisions are:

- `MATCHED`: every required validation and comparison passed with no ambiguity.
- `NEEDS_REVIEW`: at least one value is missing, inconsistent, ambiguous, unmatched, or outside
  policy tolerance.

There is no automatic rejection or approval decision.

## Matching policy

Every match run stores the full effective `matching-v1` snapshot:

| Setting | Default | Meaning |
|---|---:|---|
| Amount absolute tolerance | `0.02` | Maximum difference for monetary addition and line amounts |
| Quantity absolute tolerance | `0` | Quantities must match exactly by default |
| Unit-price relative tolerance | `0.01` | `0.01` means 1% of the PO unit price |
| Description threshold | `0.85` | Minimum normalized token similarity |
| Ambiguity margin | `0.05` | Smaller top-two score gaps require review |

If the PO unit price is zero, only an invoice unit price of exactly zero passes the unit-price
comparison. Decimal request values must be strings or integers; JSON floating-point values are
rejected. Addition checks use absolute tolerance, never percentage tolerance.

## Assignment rules

Descriptions are Unicode NFKC-normalized, case-folded, stripped of non-semantic punctuation, and
whitespace-collapsed. Unique exact normalized matches are assigned first. Remaining pairs use
RapidFuzz token-set similarity. Eligible pairs are ordered by highest score, lowest PO line number,
then lowest invoice line index and assigned one-to-one. An ambiguous or below-threshold candidate
is never assigned automatically.

## Reason codes

| Code | Condition |
|---|---|
| `INVOICE_SCHEMA_INCOMPLETE` | Required invoice value or usable line is missing/ambiguous |
| `INVOICE_LINE_ARITHMETIC_MISMATCH` | Quantity times unit price differs from line total |
| `INVOICE_SUBTOTAL_MISMATCH` | Sum of usable line totals differs from subtotal |
| `INVOICE_TOTAL_MISMATCH` | Subtotal plus tax differs from total |
| `CURRENCY_MISMATCH` | Invoice and PO currencies differ or invoice currency is unavailable |
| `DESCRIPTION_BELOW_THRESHOLD` | Best remaining description score is below policy |
| `DESCRIPTION_AMBIGUOUS` | Top candidates are too close or multiple exact matches exist |
| `INVOICE_LINE_UNMATCHED` | A line lacks a usable description or loses one-to-one assignment |
| `EXTRA_INVOICE_LINE` | No PO line remains for an invoice line |
| `PO_LINE_UNMATCHED` | A PO line has no assigned invoice line |
| `QUANTITY_MISMATCH` | Assigned quantities exceed absolute tolerance |
| `UNIT_PRICE_MISMATCH` | Assigned unit prices exceed relative tolerance |
| `LINE_AMOUNT_MISMATCH` | Invoice line amount differs from PO quantity times unit price |
| `NEGATIVE_AMOUNT` | A negative extracted financial value requires review |

Every failed check includes a human-readable message, stable decimal strings, relevant line IDs,
and available invoice evidence spans.

## API demonstration

First generate, upload, and wait for the existing synthetic invoice extraction to succeed:

```powershell
uv run python scripts/create_synthetic_invoice.py
curl.exe -F "file=@synthetic-invoice.pdf;type=application/pdf" http://localhost:8000/v1/invoices
curl.exe http://localhost:8000/v1/jobs/REPLACE_WITH_JOB_ID
```

Create a matching synthetic PO:

```powershell
curl.exe -X POST http://localhost:8000/v1/purchase-orders `
  -H "Content-Type: application/json" `
  --data-binary '{"external_po_number":"PO-DEMO-1","vendor_name":"Synthetic Vendor","currency":"INR","lines":[{"line_number":"1","description":"Industrial Filter","ordered_quantity":"2","unit_price":"500.00"},{"line_number":"2","description":"Mounting Bracket","ordered_quantity":"4","unit_price":"50.00"}]}'
```

Run and retrieve the match using returned UUIDs:

```powershell
curl.exe -X POST http://localhost:8000/v1/documents/REPLACE_WITH_DOCUMENT_ID/matches `
  -H "Content-Type: application/json" `
  --data-binary '{"purchase_order_id":"REPLACE_WITH_PO_ID"}'
curl.exe http://localhost:8000/v1/matches/REPLACE_WITH_MATCH_RUN_ID
```

The PO above produces `MATCHED` for the generated invoice. To demonstrate `NEEDS_REVIEW`, create a
second PO with currency `USD` or change a unit price beyond tolerance, then repeat the match call
with that PO ID. Repeating the same document/PO match returns HTTP 200 and the same match-run ID;
the first request returns HTTP 201.

## Verification and limitations

```powershell
uv run pytest -m "not docker and not docile" -q -p no:cacheprovider
uv run ruff check .
uv run mypy apps invoiceops workers
uv run python scripts/run_matching_evaluation.py
docker compose --profile test up --build --abort-on-container-exit --exit-code-from integration-tests integration-tests
```

The synthetic scenario report is not a claim about production accuracy. Vendor identity is not
currently compared because vendor extraction is outside this slice. Tax presence and invoice
arithmetic are validated, but jurisdiction-specific tax policy is not implemented. Existing
synthetic extraction and DocILE reports remain separate and unchanged.
