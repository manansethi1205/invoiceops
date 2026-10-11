# Opt-in deterministic financial-summary guard

Counts use present total labels as the outcome denominator, all documents for review/unchanged outputs, and emitted wrong totals for the role-error subset. Financial review is the existing mandatory pre-PO validation gate; actual PO matching and payment decisions are not evaluated. This observed corpus is development data, not a holdout. No hybrid/VLM fix or live-provider claim.

```json
{
  "metric_version": "financial-summary-guard-paired-v1",
  "corpus_fingerprint": "20adbcfa757d37ca3fc5df915d25ea0459c33e33f8752b2d407e6e665a6feaa9",
  "source_revision": "30025e2233bd277430c0ba20c7dee6aedb810f5f",
  "source_state": "working-tree changes",
  "baseline_name": "deterministic-baseline",
  "baseline_version": "0.2.0",
  "candidate_name": "deterministic-financial-summary-guard",
  "candidate_version": "0.3.0",
  "documents": 29,
  "pages": 29,
  "ocr_documents": 1,
  "baseline": {
    "documents": 29,
    "present": 28,
    "absent": 1,
    "unannotated": 0,
    "correct": 0,
    "wrong": 14,
    "ambiguous": 14,
    "missing": 0,
    "failed_present": 0,
    "correct_absence": 1,
    "false_on_absent": 0,
    "failed_documents": 0,
    "wrong_equals_subtotal": 14,
    "location_supported_role_errors": 12,
    "mandatory_financial_review": 29,
    "total_incomplete_review_gate": 15
  },
  "candidate": {
    "documents": 29,
    "present": 28,
    "absent": 1,
    "unannotated": 0,
    "correct": 0,
    "wrong": 0,
    "ambiguous": 28,
    "missing": 0,
    "failed_present": 0,
    "correct_absence": 1,
    "false_on_absent": 0,
    "failed_documents": 0,
    "wrong_equals_subtotal": 0,
    "location_supported_role_errors": 0,
    "mandatory_financial_review": 29,
    "total_incomplete_review_gate": 29
  },
  "added_abstentions": 14,
  "added_mandatory_review": 0,
  "unchanged_non_total_documents": 29,
  "unchanged_invoice_number_documents": 29,
  "unchanged_invoice_date_documents": 29,
  "unchanged_row_documents": 29,
  "matched_summary": "not evaluated: no authorized PO/receipt corpus",
  "limitations": "observed-development-deterministic-only-no-hybrid-claim"
}
```
