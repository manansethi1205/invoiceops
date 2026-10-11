# Guarded synthetic hybrid benchmark

Aggregate counts only. Rates with zero denominators are null. This is synthetic evaluation, not production or DocILE evidence.

```json
{
  "mode": "synthetic-local",
  "local_provider_version": "label-guided-stub-v1",
  "source_input_mode": "synthetic-scan-tokens",
  "corpus_version": "synthetic-live-financial-roles-v1",
  "corpus_fingerprint": "2936c05503d82bd66add5a380f480f39c2cfbedf27ca4e422d0e93b81941137e",
  "corpus_seed": 20261011,
  "partition": "all",
  "documents": 16,
  "pages": 17,
  "ocr_documents": 0,
  "synthetic_scan_documents": 2,
  "max_documents": 16,
  "max_pages": 17,
  "source_revision": "68ff26e1df9d977d012fee2c87fb9c0282c23b17",
  "source_state": "working-tree changes",
  "deterministic_version": "0.2.0",
  "hybrid_version": "0.5.0",
  "schema_version": "invoice-v2",
  "prompt_version": "invoice-vision-v1",
  "matching_policy": "matching-v3",
  "price_assumptions": null,
  "metrics": {
    "all": {
      "deterministic": {
        "documents": 16,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "currency": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "tax": {
            "numerator": 0,
            "denominator": 16,
            "rate": 0.0
          },
          "total": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          }
        },
        "line_tp": 4,
        "line_fp": 12,
        "line_fn": 28,
        "predicted_lines": 16,
        "labelled_lines": 32,
        "line_precision": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "line_recall": {
          "numerator": 4,
          "denominator": 32,
          "rate": 0.125
        },
        "line_f1": {
          "numerator": 8,
          "denominator": 48,
          "rate": 0.16666666666666666
        },
        "review_documents": 16,
        "matched_documents": 0,
        "expected_review_documents": 16,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 16,
          "rate": 0.0
        },
        "p50_total_latency_ms": 10.84120012819767,
        "p95_total_latency_ms": 18.732799915596843
      },
      "hybrid": {
        "documents": 16,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "currency": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "tax": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          },
          "total": {
            "numerator": 16,
            "denominator": 16,
            "rate": 1.0
          }
        },
        "line_tp": 14,
        "line_fp": 2,
        "line_fn": 18,
        "predicted_lines": 16,
        "labelled_lines": 32,
        "line_precision": {
          "numerator": 14,
          "denominator": 16,
          "rate": 0.875
        },
        "line_recall": {
          "numerator": 14,
          "denominator": 32,
          "rate": 0.4375
        },
        "line_f1": {
          "numerator": 28,
          "denominator": 48,
          "rate": 0.5833333333333334
        },
        "review_documents": 12,
        "matched_documents": 4,
        "expected_review_documents": 16,
        "false_automatic_matches": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "p50_total_latency_ms": 87.31270022690296,
        "p95_total_latency_ms": 216.84690029360354
      },
      "safety": {
        "candidate_value_attempts": 216,
        "grounded_values": 216,
        "grounded_value_acceptance": {
          "numerator": 216,
          "denominator": 216,
          "rate": 1.0
        },
        "candidate_rows": 32,
        "associated_rows": 16,
        "deterministic_rows_considered": 16,
        "correct_associations": 16,
        "incorrect_associations": 0,
        "unscorable_associations": 0,
        "row_association_precision": {
          "numerator": 16,
          "denominator": 16,
          "rate": 1.0
        },
        "row_association_coverage": {
          "numerator": 16,
          "denominator": 32,
          "rate": 0.5
        },
        "deterministic_row_association_coverage": {
          "numerator": 16,
          "denominator": 16,
          "rate": 1.0
        },
        "row_abstention": {
          "numerator": 16,
          "denominator": 32,
          "rate": 0.5
        },
        "disagreement_cells": 2,
        "promoted_cells": 28,
        "numeric_promoted_cells": 28,
        "wrong_financial_value_promotions": 0,
        "wrong_financial_role_promotions": 0,
        "line_promoted_cells": 12,
        "false_value_promotions": {
          "numerator": 0,
          "denominator": 28,
          "rate": 0.0
        },
        "false_financial_promotions": {
          "numerator": 0,
          "denominator": 28,
          "rate": 0.0
        },
        "false_cross_row_promotions": {
          "numerator": 0,
          "denominator": 12,
          "rate": 0.0
        },
        "unscorable_promotions": 0,
        "unscorable_numeric_promotions": 0,
        "unscorable_line_promotions": 0,
        "unresolved_row_documents": 8,
        "unresolved_row_review_documents": 8,
        "unresolved_row_false_automatic_matches": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "eligible_documents": 16,
        "provider_requests": 16,
        "successful_responses": 16,
        "provider_failures": 0,
        "budget_refused_documents": 0,
        "provider_failure_rate": {
          "numerator": 0,
          "denominator": 16,
          "rate": 0.0
        },
        "p50_provider_latency_ms": 0.20999996922910213,
        "p95_provider_latency_ms": 0.48530008643865585
      }
    },
    "development": {
      "deterministic": {
        "documents": 8,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "currency": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "tax": {
            "numerator": 0,
            "denominator": 8,
            "rate": 0.0
          },
          "total": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          }
        },
        "line_tp": 0,
        "line_fp": 12,
        "line_fn": 16,
        "predicted_lines": 12,
        "labelled_lines": 16,
        "line_precision": {
          "numerator": 0,
          "denominator": 12,
          "rate": 0.0
        },
        "line_recall": {
          "numerator": 0,
          "denominator": 16,
          "rate": 0.0
        },
        "line_f1": {
          "numerator": 0,
          "denominator": 28,
          "rate": 0.0
        },
        "review_documents": 8,
        "matched_documents": 0,
        "expected_review_documents": 8,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "p50_total_latency_ms": 11.290400056168437,
        "p95_total_latency_ms": 18.732799915596843
      },
      "hybrid": {
        "documents": 8,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "currency": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "tax": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "total": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          }
        },
        "line_tp": 10,
        "line_fp": 2,
        "line_fn": 6,
        "predicted_lines": 12,
        "labelled_lines": 16,
        "line_precision": {
          "numerator": 10,
          "denominator": 12,
          "rate": 0.8333333333333334
        },
        "line_recall": {
          "numerator": 10,
          "denominator": 16,
          "rate": 0.625
        },
        "line_f1": {
          "numerator": 20,
          "denominator": 28,
          "rate": 0.7142857142857143
        },
        "review_documents": 4,
        "matched_documents": 4,
        "expected_review_documents": 8,
        "false_automatic_matches": {
          "numerator": 4,
          "denominator": 8,
          "rate": 0.5
        },
        "p50_total_latency_ms": 87.31270022690296,
        "p95_total_latency_ms": 117.24100029096007
      },
      "safety": {
        "candidate_value_attempts": 108,
        "grounded_values": 108,
        "grounded_value_acceptance": {
          "numerator": 108,
          "denominator": 108,
          "rate": 1.0
        },
        "candidate_rows": 16,
        "associated_rows": 12,
        "deterministic_rows_considered": 12,
        "correct_associations": 12,
        "incorrect_associations": 0,
        "unscorable_associations": 0,
        "row_association_precision": {
          "numerator": 12,
          "denominator": 12,
          "rate": 1.0
        },
        "row_association_coverage": {
          "numerator": 12,
          "denominator": 16,
          "rate": 0.75
        },
        "deterministic_row_association_coverage": {
          "numerator": 12,
          "denominator": 12,
          "rate": 1.0
        },
        "row_abstention": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "disagreement_cells": 2,
        "promoted_cells": 20,
        "numeric_promoted_cells": 20,
        "wrong_financial_value_promotions": 0,
        "wrong_financial_role_promotions": 0,
        "line_promoted_cells": 12,
        "false_value_promotions": {
          "numerator": 0,
          "denominator": 20,
          "rate": 0.0
        },
        "false_financial_promotions": {
          "numerator": 0,
          "denominator": 20,
          "rate": 0.0
        },
        "false_cross_row_promotions": {
          "numerator": 0,
          "denominator": 12,
          "rate": 0.0
        },
        "unscorable_promotions": 0,
        "unscorable_numeric_promotions": 0,
        "unscorable_line_promotions": 0,
        "unresolved_row_documents": 2,
        "unresolved_row_review_documents": 2,
        "unresolved_row_false_automatic_matches": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "eligible_documents": 8,
        "provider_requests": 8,
        "successful_responses": 8,
        "provider_failures": 0,
        "budget_refused_documents": 0,
        "provider_failure_rate": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "p50_provider_latency_ms": 0.20999996922910213,
        "p95_provider_latency_ms": 0.45030005276203156
      }
    },
    "unseen": {
      "deterministic": {
        "documents": 8,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "currency": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "tax": {
            "numerator": 0,
            "denominator": 8,
            "rate": 0.0
          },
          "total": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          }
        },
        "line_tp": 4,
        "line_fp": 0,
        "line_fn": 12,
        "predicted_lines": 4,
        "labelled_lines": 16,
        "line_precision": {
          "numerator": 4,
          "denominator": 4,
          "rate": 1.0
        },
        "line_recall": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "line_f1": {
          "numerator": 8,
          "denominator": 20,
          "rate": 0.4
        },
        "review_documents": 8,
        "matched_documents": 0,
        "expected_review_documents": 8,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "p50_total_latency_ms": 9.879800025373697,
        "p95_total_latency_ms": 11.375500122085214
      },
      "hybrid": {
        "documents": 8,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "currency": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "tax": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          },
          "total": {
            "numerator": 8,
            "denominator": 8,
            "rate": 1.0
          }
        },
        "line_tp": 4,
        "line_fp": 0,
        "line_fn": 12,
        "predicted_lines": 4,
        "labelled_lines": 16,
        "line_precision": {
          "numerator": 4,
          "denominator": 4,
          "rate": 1.0
        },
        "line_recall": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "line_f1": {
          "numerator": 8,
          "denominator": 20,
          "rate": 0.4
        },
        "review_documents": 8,
        "matched_documents": 0,
        "expected_review_documents": 8,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "p50_total_latency_ms": 83.93940050154924,
        "p95_total_latency_ms": 216.84690029360354
      },
      "safety": {
        "candidate_value_attempts": 108,
        "grounded_values": 108,
        "grounded_value_acceptance": {
          "numerator": 108,
          "denominator": 108,
          "rate": 1.0
        },
        "candidate_rows": 16,
        "associated_rows": 4,
        "deterministic_rows_considered": 4,
        "correct_associations": 4,
        "incorrect_associations": 0,
        "unscorable_associations": 0,
        "row_association_precision": {
          "numerator": 4,
          "denominator": 4,
          "rate": 1.0
        },
        "row_association_coverage": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "deterministic_row_association_coverage": {
          "numerator": 4,
          "denominator": 4,
          "rate": 1.0
        },
        "row_abstention": {
          "numerator": 12,
          "denominator": 16,
          "rate": 0.75
        },
        "disagreement_cells": 0,
        "promoted_cells": 8,
        "numeric_promoted_cells": 8,
        "wrong_financial_value_promotions": 0,
        "wrong_financial_role_promotions": 0,
        "line_promoted_cells": 0,
        "false_value_promotions": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "false_financial_promotions": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "false_cross_row_promotions": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "unscorable_promotions": 0,
        "unscorable_numeric_promotions": 0,
        "unscorable_line_promotions": 0,
        "unresolved_row_documents": 6,
        "unresolved_row_review_documents": 6,
        "unresolved_row_false_automatic_matches": {
          "numerator": 0,
          "denominator": 6,
          "rate": 0.0
        },
        "eligible_documents": 8,
        "provider_requests": 8,
        "successful_responses": 8,
        "provider_failures": 0,
        "budget_refused_documents": 0,
        "provider_failure_rate": {
          "numerator": 0,
          "denominator": 8,
          "rate": 0.0
        },
        "p50_provider_latency_ms": 0.2093999646604061,
        "p95_provider_latency_ms": 0.48530008643865585
      }
    }
  },
  "usage": {
    "requests": 16,
    "known_usage_requests": 16,
    "unknown_usage_requests": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "complete": true,
    "known_usage_cost_usd": "0",
    "estimated_total_cost_usd": "0",
    "spending_limit_usd": "0",
    "accounted_cost_upper_bound_usd": "0",
    "per_request_reserved_upper_bound_usd": "0",
    "max_output_tokens": 0,
    "input_charge_token_bound": 0,
    "accounting_halted": false
  },
  "limitations": [
    "No model, SDK, credentials or network client is initialized; zero API calls and cost.",
    "Requests and response counts denote local fixture invocations, not provider API calls.",
    "Label-guided oracle candidates exercise grounding/fusion; these are not model accuracy, generalization, provider latency or token-usage measurements.",
    "Synthetic scan tokens come from corpus labels only when explicitly selected; they are not measured OCR output. PDFs use native embedded-text extraction.",
    "Ambiguous/missing roles remain null; candidates do not infer values from arithmetic.",
    "Synthetic layouts only; no live quality is inferred from fake-provider tests.",
    "Unseen families are reserved layouts, not a population or independent business holdout.",
    "Grounding validates copied values, not financial semantics; role errors are measured against source labels.",
    "Association precision counts unscorable accepted associations against precision; they are also shown separately.",
    "Budget-skipped and failed documents retain deterministic output and remain in paired denominators.",
    "Routing is hybrid-routed 0.5.0; complete unrouted documents are not sent to the provider."
  ]
}
```
