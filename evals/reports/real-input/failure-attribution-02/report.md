# Private invoice failure attribution

Evaluation-only observational stages, not confirmed root causes. The sample is observed development data. See the failure-attribution guide for definitions, denominators and limitations. No arithmetic or model calls.

```json
{
  "metric_version": "real-input-attribution-v1",
  "corpus_fingerprint": "20adbcfa757d37ca3fc5df915d25ea0459c33e33f8752b2d407e6e665a6feaa9",
  "source_revision": "32e193eb7d0840d597e2ea1c12e1362a59d33e83",
  "source_state": "working-tree changes",
  "extractor_version": "0.2.0",
  "definitions": {
    "tally_denominator": "all label opportunities; present/absent scored; unannotated excluded",
    "signals_denominator": "present labels only; stages are independent observable signals",
    "source": "unique minimal contiguous normalized token span inside human boxes; bounded probe",
    "regions": "existing header-label or table-header detector on label page; not causal",
    "row_identity": "unique evidence containment of labelled source tokens; no index or arithmetic",
    "confusion": "emitted total equals distinct present subtotal; location support separately counted",
    "scorer_only": "location-associated exact row absent from order-preserving exact alignment"
  },
  "attempted_documents": 29,
  "failed_documents": 0,
  "pages": 29,
  "ocr_documents": 1,
  "ocr_available": true,
  "slices": {
    "all": {
      "documents": 29,
      "headers": {
        "invoice_number": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "correct": 28
          },
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 28,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 28,
          "candidate_emitted": 28,
          "resolved_value_emitted": 28,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "invoice_date": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "correct": 28
          },
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 28,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 28,
          "candidate_emitted": 28,
          "resolved_value_emitted": 28,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "currency": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "tokens_not_observed": 14,
            "annotation_or_tokens_unresolved": 14
          },
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 14,
          "source_unresolved": 14,
          "region_detected_on_label_page": 28,
          "candidate_emitted": 5,
          "resolved_value_emitted": 5,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "subtotal": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "candidate_not_emitted": 14,
            "region_not_detected": 14
          },
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 28,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "tax": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "excluded_unannotated": 27,
            "candidate_not_emitted": 1
          },
          "present": 1,
          "absent": 1,
          "not_annotated": 27,
          "source_found": 1,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 1,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "total": {
          "denominator": 29,
          "categories": {
            "correct_absence": 1,
            "ambiguous_candidate": 14,
            "wrong_role": 12,
            "wrong_value": 2
          },
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 28,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 28,
          "candidate_emitted": 28,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        }
      },
      "cells": {
        "description": {
          "denominator": 50,
          "categories": {
            "region_not_detected": 17,
            "wrong_value": 15,
            "evidence_unresolved": 16,
            "candidate_not_emitted": 2
          },
          "present": 50,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 50,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 33,
          "candidate_emitted": 15,
          "resolved_value_emitted": 15,
          "associated_row_emitted": 15,
          "displaced_value_evidence": 0
        },
        "quantity": {
          "denominator": 50,
          "categories": {
            "absence_unscorable": 25,
            "region_not_detected": 1,
            "candidate_not_emitted": 11,
            "correct_absence": 4,
            "evidence_unresolved": 9
          },
          "present": 21,
          "absent": 29,
          "not_annotated": 0,
          "source_found": 21,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 20,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 11,
          "displaced_value_evidence": 0
        },
        "unit_price": {
          "denominator": 50,
          "categories": {
            "absence_unscorable": 35,
            "correct_absence": 15
          },
          "present": 0,
          "absent": 50,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "line_total": {
          "denominator": 50,
          "categories": {
            "region_not_detected": 17,
            "wrong_value": 15,
            "evidence_unresolved": 16,
            "candidate_not_emitted": 2
          },
          "present": 50,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 50,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 33,
          "candidate_emitted": 15,
          "resolved_value_emitted": 15,
          "associated_row_emitted": 15,
          "displaced_value_evidence": 15
        }
      },
      "rows_denominator": 50,
      "rows": {
        "no_detected_header": 17,
        "wrong_row_values": 15,
        "ambiguous_association": 16,
        "detected_no_associated_row": 2
      },
      "predicted_rows": 22,
      "associated_predicted_rows": 15,
      "unassociated_predicted_rows": 0,
      "ambiguous_predicted_rows": 7,
      "predicted_rows_with_wrong_column_semantics": 0,
      "predicted_rows_with_displaced_cells": 15,
      "total_present": 28,
      "total_emitted": 14,
      "total_equals_subtotal": 14,
      "total_equals_subtotal_location_supported": 12,
      "total_subtotal_equal_labels": 0,
      "absent_tables": 1,
      "unannotated_tables": 0,
      "labelled_table_documents": 28,
      "labelled_table_documents_without_emitted_rows": 17,
      "labelled_table_documents_without_detected_header": 15,
      "visual_rows": 667,
      "visual_stages": {
        "before_header": 483,
        "header": 13,
        "probable_item": 22,
        "no_numeric_support": 66,
        "description_only": 77,
        "missing_description": 6
      }
    },
    "no_detected_table_header": {
      "documents": 15,
      "headers": {
        "invoice_number": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "correct": 14
          },
          "present": 14,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "invoice_date": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "correct": 14
          },
          "present": 14,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "currency": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "tokens_not_observed": 14
          },
          "present": 14,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 14,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "subtotal": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "candidate_not_emitted": 14
          },
          "present": 14,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "tax": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "excluded_unannotated": 14
          },
          "present": 0,
          "absent": 1,
          "not_annotated": 14,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "total": {
          "denominator": 15,
          "categories": {
            "correct_absence": 1,
            "ambiguous_candidate": 14
          },
          "present": 14,
          "absent": 1,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        }
      },
      "cells": {
        "description": {
          "denominator": 14,
          "categories": {
            "region_not_detected": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "quantity": {
          "denominator": 14,
          "categories": {
            "absence_unscorable": 14
          },
          "present": 0,
          "absent": 14,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "unit_price": {
          "denominator": 14,
          "categories": {
            "absence_unscorable": 14
          },
          "present": 0,
          "absent": 14,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "line_total": {
          "denominator": 14,
          "categories": {
            "region_not_detected": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        }
      },
      "rows_denominator": 14,
      "rows": {
        "no_detected_header": 14
      },
      "predicted_rows": 0,
      "associated_predicted_rows": 0,
      "unassociated_predicted_rows": 0,
      "ambiguous_predicted_rows": 0,
      "predicted_rows_with_wrong_column_semantics": 0,
      "predicted_rows_with_displaced_cells": 0,
      "total_present": 14,
      "total_emitted": 0,
      "total_equals_subtotal": 0,
      "total_equals_subtotal_location_supported": 0,
      "total_subtotal_equal_labels": 0,
      "absent_tables": 1,
      "unannotated_tables": 0,
      "labelled_table_documents": 14,
      "labelled_table_documents_without_emitted_rows": 14,
      "labelled_table_documents_without_detected_header": 14,
      "visual_rows": 261,
      "visual_stages": {
        "before_header": 261
      }
    },
    "net_tax_gross_token_signature": {
      "documents": 14,
      "headers": {
        "invoice_number": {
          "denominator": 14,
          "categories": {
            "correct": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "invoice_date": {
          "denominator": 14,
          "categories": {
            "correct": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "currency": {
          "denominator": 14,
          "categories": {
            "annotation_or_tokens_unresolved": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 14,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 5,
          "resolved_value_emitted": 5,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "subtotal": {
          "denominator": 14,
          "categories": {
            "region_not_detected": 14
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "tax": {
          "denominator": 14,
          "categories": {
            "excluded_unannotated": 13,
            "candidate_not_emitted": 1
          },
          "present": 1,
          "absent": 0,
          "not_annotated": 13,
          "source_found": 1,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 1,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "total": {
          "denominator": 14,
          "categories": {
            "wrong_role": 12,
            "wrong_value": 2
          },
          "present": 14,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 14,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 14,
          "candidate_emitted": 14,
          "resolved_value_emitted": 14,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        }
      },
      "cells": {
        "description": {
          "denominator": 36,
          "categories": {
            "region_not_detected": 3,
            "wrong_value": 15,
            "evidence_unresolved": 16,
            "candidate_not_emitted": 2
          },
          "present": 36,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 36,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 33,
          "candidate_emitted": 15,
          "resolved_value_emitted": 15,
          "associated_row_emitted": 15,
          "displaced_value_evidence": 0
        },
        "quantity": {
          "denominator": 36,
          "categories": {
            "region_not_detected": 1,
            "absence_unscorable": 11,
            "candidate_not_emitted": 11,
            "correct_absence": 4,
            "evidence_unresolved": 9
          },
          "present": 21,
          "absent": 15,
          "not_annotated": 0,
          "source_found": 21,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 20,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 11,
          "displaced_value_evidence": 0
        },
        "unit_price": {
          "denominator": 36,
          "categories": {
            "absence_unscorable": 21,
            "correct_absence": 15
          },
          "present": 0,
          "absent": 36,
          "not_annotated": 0,
          "source_found": 0,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 0,
          "candidate_emitted": 0,
          "resolved_value_emitted": 0,
          "associated_row_emitted": 0,
          "displaced_value_evidence": 0
        },
        "line_total": {
          "denominator": 36,
          "categories": {
            "region_not_detected": 3,
            "wrong_value": 15,
            "evidence_unresolved": 16,
            "candidate_not_emitted": 2
          },
          "present": 36,
          "absent": 0,
          "not_annotated": 0,
          "source_found": 36,
          "source_not_observed": 0,
          "source_unresolved": 0,
          "region_detected_on_label_page": 33,
          "candidate_emitted": 15,
          "resolved_value_emitted": 15,
          "associated_row_emitted": 15,
          "displaced_value_evidence": 15
        }
      },
      "rows_denominator": 36,
      "rows": {
        "no_detected_header": 3,
        "wrong_row_values": 15,
        "ambiguous_association": 16,
        "detected_no_associated_row": 2
      },
      "predicted_rows": 22,
      "associated_predicted_rows": 15,
      "unassociated_predicted_rows": 0,
      "ambiguous_predicted_rows": 7,
      "predicted_rows_with_wrong_column_semantics": 0,
      "predicted_rows_with_displaced_cells": 15,
      "total_present": 14,
      "total_emitted": 14,
      "total_equals_subtotal": 14,
      "total_equals_subtotal_location_supported": 12,
      "total_subtotal_equal_labels": 0,
      "absent_tables": 0,
      "unannotated_tables": 0,
      "labelled_table_documents": 14,
      "labelled_table_documents_without_emitted_rows": 3,
      "labelled_table_documents_without_detected_header": 1,
      "visual_rows": 406,
      "visual_stages": {
        "before_header": 222,
        "header": 13,
        "probable_item": 22,
        "no_numeric_support": 66,
        "description_only": 77,
        "missing_description": 6
      }
    }
  },
  "limitations": "observational-development-audit-not-causal"
}
```
