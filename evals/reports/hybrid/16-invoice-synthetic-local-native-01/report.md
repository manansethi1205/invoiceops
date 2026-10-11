# Guarded synthetic hybrid benchmark

Aggregate counts only. Rates with zero denominators are null. This is synthetic evaluation, not production or DocILE evidence.

```json
{
  "metric_version": "synthetic-source-safety-v2",
  "mode": "synthetic-local",
  "local_provider_version": "label-guided-stub-v1",
  "source_input_mode": "native",
  "corpus_version": "synthetic-live-financial-roles-v1",
  "corpus_fingerprint": "2936c05503d82bd66add5a380f480f39c2cfbedf27ca4e422d0e93b81941137e",
  "corpus_seed": 20261011,
  "partition": "all",
  "documents": 16,
  "pages": 17,
  "ocr_documents": 2,
  "ocr_engine": "tesseract",
  "ocr_engine_version": "tesseract v5.5.3.20260724",
  "ocr_version_source": "runtime-cli",
  "ocr_backend": "pymupdf-tesseract",
  "ocr_backend_version": "1.28.2",
  "synthetic_scan_documents": 0,
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
        "p50_total_latency_ms": 13.436199864372611,
        "p95_total_latency_ms": 1472.5677000824362
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
        "expected_review_documents": 12,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 12,
          "rate": 0.0
        },
        "p50_total_latency_ms": 132.3049000930041,
        "p95_total_latency_ms": 1945.417100097984
      },
      "safety": {
        "candidate_value_attempts": 216,
        "grounded_values": 215,
        "grounded_value_acceptance": {
          "numerator": 215,
          "denominator": 216,
          "rate": 0.9953703703703703
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
        "p50_provider_latency_ms": 0.29390002600848675,
        "p95_provider_latency_ms": 0.682199839502573
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
        "p50_total_latency_ms": 9.973099920898676,
        "p95_total_latency_ms": 27.05699997022748
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
        "expected_review_documents": 4,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "p50_total_latency_ms": 93.22070004418492,
        "p95_total_latency_ms": 164.78620003908873
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
        "p50_provider_latency_ms": 0.29729981906712055,
        "p95_provider_latency_ms": 0.682199839502573
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
        "p50_total_latency_ms": 15.342599945142865,
        "p95_total_latency_ms": 1472.5677000824362
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
        "p50_total_latency_ms": 146.80169965140522,
        "p95_total_latency_ms": 1945.417100097984
      },
      "safety": {
        "candidate_value_attempts": 108,
        "grounded_values": 107,
        "grounded_value_acceptance": {
          "numerator": 107,
          "denominator": 108,
          "rate": 0.9907407407407407
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
        "p50_provider_latency_ms": 0.24289987049996853,
        "p95_provider_latency_ms": 0.47149998135864735
      }
    }
  },
  "metrics_by_input_type": {
    "pdf": {
      "deterministic": {
        "documents": 14,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "currency": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "tax": {
            "numerator": 0,
            "denominator": 14,
            "rate": 0.0
          },
          "total": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          }
        },
        "line_tp": 4,
        "line_fp": 12,
        "line_fn": 24,
        "predicted_lines": 16,
        "labelled_lines": 28,
        "line_precision": {
          "numerator": 4,
          "denominator": 16,
          "rate": 0.25
        },
        "line_recall": {
          "numerator": 4,
          "denominator": 28,
          "rate": 0.14285714285714285
        },
        "line_f1": {
          "numerator": 8,
          "denominator": 44,
          "rate": 0.18181818181818182
        },
        "review_documents": 14,
        "matched_documents": 0,
        "expected_review_documents": 14,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 14,
          "rate": 0.0
        },
        "p50_total_latency_ms": 10.731399990618229,
        "p95_total_latency_ms": 27.05699997022748
      },
      "hybrid": {
        "documents": 14,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "currency": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "tax": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          },
          "total": {
            "numerator": 14,
            "denominator": 14,
            "rate": 1.0
          }
        },
        "line_tp": 14,
        "line_fp": 2,
        "line_fn": 14,
        "predicted_lines": 16,
        "labelled_lines": 28,
        "line_precision": {
          "numerator": 14,
          "denominator": 16,
          "rate": 0.875
        },
        "line_recall": {
          "numerator": 14,
          "denominator": 28,
          "rate": 0.5
        },
        "line_f1": {
          "numerator": 28,
          "denominator": 44,
          "rate": 0.6363636363636364
        },
        "review_documents": 10,
        "matched_documents": 4,
        "expected_review_documents": 10,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 10,
          "rate": 0.0
        },
        "p50_total_latency_ms": 130.94980013556778,
        "p95_total_latency_ms": 164.8772000335157
      },
      "safety": {
        "candidate_value_attempts": 188,
        "grounded_values": 188,
        "grounded_value_acceptance": {
          "numerator": 188,
          "denominator": 188,
          "rate": 1.0
        },
        "candidate_rows": 28,
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
          "denominator": 28,
          "rate": 0.5714285714285714
        },
        "deterministic_row_association_coverage": {
          "numerator": 16,
          "denominator": 16,
          "rate": 1.0
        },
        "row_abstention": {
          "numerator": 12,
          "denominator": 28,
          "rate": 0.42857142857142855
        },
        "disagreement_cells": 2,
        "promoted_cells": 26,
        "numeric_promoted_cells": 26,
        "wrong_financial_value_promotions": 0,
        "wrong_financial_role_promotions": 0,
        "line_promoted_cells": 12,
        "false_value_promotions": {
          "numerator": 0,
          "denominator": 26,
          "rate": 0.0
        },
        "false_financial_promotions": {
          "numerator": 0,
          "denominator": 26,
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
        "unresolved_row_documents": 6,
        "unresolved_row_review_documents": 6,
        "unresolved_row_false_automatic_matches": {
          "numerator": 0,
          "denominator": 6,
          "rate": 0.0
        },
        "eligible_documents": 14,
        "provider_requests": 14,
        "successful_responses": 14,
        "provider_failures": 0,
        "budget_refused_documents": 0,
        "provider_failure_rate": {
          "numerator": 0,
          "denominator": 14,
          "rate": 0.0
        },
        "p50_provider_latency_ms": 0.26989984326064587,
        "p95_provider_latency_ms": 0.682199839502573
      }
    },
    "png": {
      "deterministic": {
        "documents": 2,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "currency": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "tax": {
            "numerator": 0,
            "denominator": 2,
            "rate": 0.0
          },
          "total": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          }
        },
        "line_tp": 0,
        "line_fp": 0,
        "line_fn": 4,
        "predicted_lines": 0,
        "labelled_lines": 4,
        "line_precision": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "line_recall": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "line_f1": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "review_documents": 2,
        "matched_documents": 0,
        "expected_review_documents": 2,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "p50_total_latency_ms": 1254.5175000559539,
        "p95_total_latency_ms": 1472.5677000824362
      },
      "hybrid": {
        "documents": 2,
        "header_exact_match": {
          "invoice_number": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "invoice_date": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "currency": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "subtotal": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "tax": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          },
          "total": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0
          }
        },
        "line_tp": 0,
        "line_fp": 0,
        "line_fn": 4,
        "predicted_lines": 0,
        "labelled_lines": 4,
        "line_precision": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "line_recall": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "line_f1": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "review_documents": 2,
        "matched_documents": 0,
        "expected_review_documents": 2,
        "false_automatic_matches": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "p50_total_latency_ms": 1644.569199765101,
        "p95_total_latency_ms": 1945.417100097984
      },
      "safety": {
        "candidate_value_attempts": 28,
        "grounded_values": 27,
        "grounded_value_acceptance": {
          "numerator": 27,
          "denominator": 28,
          "rate": 0.9642857142857143
        },
        "candidate_rows": 4,
        "associated_rows": 0,
        "deterministic_rows_considered": 0,
        "correct_associations": 0,
        "incorrect_associations": 0,
        "unscorable_associations": 0,
        "row_association_precision": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "row_association_coverage": {
          "numerator": 0,
          "denominator": 4,
          "rate": 0.0
        },
        "deterministic_row_association_coverage": {
          "numerator": 0,
          "denominator": 0,
          "rate": null
        },
        "row_abstention": {
          "numerator": 4,
          "denominator": 4,
          "rate": 1.0
        },
        "disagreement_cells": 0,
        "promoted_cells": 2,
        "numeric_promoted_cells": 2,
        "wrong_financial_value_promotions": 0,
        "wrong_financial_role_promotions": 0,
        "line_promoted_cells": 0,
        "false_value_promotions": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "false_financial_promotions": {
          "numerator": 0,
          "denominator": 2,
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
        "unresolved_row_documents": 2,
        "unresolved_row_review_documents": 2,
        "unresolved_row_false_automatic_matches": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "eligible_documents": 2,
        "provider_requests": 2,
        "successful_responses": 2,
        "provider_failures": 0,
        "budget_refused_documents": 0,
        "provider_failure_rate": {
          "numerator": 0,
          "denominator": 2,
          "rate": 0.0
        },
        "p50_provider_latency_ms": 0.4686999600380659,
        "p95_provider_latency_ms": 0.47149998135864735
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
    "OCR engine version is the runtime CLI readiness version; native text extraction uses integrated PyMuPDF/Tesseract. Its backend version is recorded separately; the integrated Tesseract library version is not exposed by this API.",
    "Routing is hybrid-routed 0.5.0; complete unrouted documents are not sent to the provider."
  ]
}
```
