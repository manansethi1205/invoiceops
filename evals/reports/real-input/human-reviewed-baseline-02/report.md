# Private human-labelled deterministic benchmark

This run uses the user's updated annotations after their confirmation of human
review. The labels originated as AI-assisted drafts; this is not independent
blinded annotation. The staging step preserved the original files and changed
only the private copy's provenance marker to record the user's attestation.
Annotation quality and real-world document origin have not been independently
verified. This sample is observed development data, not an independent holdout.

Compared with the first baseline, all 29 document byte hashes are unchanged and
14 annotations changed. The annotation-inclusive corpus fingerprint therefore
changed. Currency evidence support improved from zero to five of five correct
currency predictions. Exact value and complete item-row counts are unchanged;
this is an annotation update, not an extraction improvement. Both runs and
private corpus snapshots are retained separately.

There are 29 PDFs, 29 pages and 50 fully labelled item rows. Exact row scoring
requires all four canonical cells to match, so zero exact rows does not imply
every cell was wrong. Tax is unannotated on 27 documents and excluded from that
field's denominator. The single OCR document has no present header labels or
labelled item rows, so it cannot establish scan extraction accuracy.

External provider/client imports and Python network connections were blocked.
No model calls, API tokens or costs occurred. This benchmark does not evaluate
matching, review, risk or payment decisions.

Value exact uses existing canonical normalization; evidence support is separate,
not DocILE location scoring. Header coverage is extracted/present; present accuracy is
value-exact/present; conditional accuracy is value-exact/extracted-on-present. Explicit absence
is correct only when a schema-valid output abstains; failed documents receive no absence credit.
Unannotated fields are excluded. Exact rows use existing order-preserving DP alignment and all
four canonical cells, including explicitly absent cells. Entire partially labelled tables are
excluded from row precision/recall, with exclusion counts. FP=predicted-TP, FN=labelled-TP,
F1=2TP/(labelled+predicted); zero denominators are null. Supported evidence additionally requires
each human box center inside a same-page predicted span with text matching its source tokens.
Scan/ocr includes any attempted OCR, including mixed PDFs and failed OCR; embedded-only requires
completed text extraction with no OCR; other failures are unknown. Latency includes failures,
nearest-rank p50/p95, metadata probing plus extraction/schema validation. Known pages include
decodable documents
even if OCR fails. OCR completed pages can include partial progress before a later failure.
OCR CLI readiness version does not identify the integrated Tesseract library version; PyMuPDF
backend version is reported separately. Human provenance is an attestation, not independently
verified authorship. Small selected private corpora are diagnostic, not population/holdout
accuracy. No model, supplier/PO discovery, matching, review, approval or payment is evaluated.

```json
{
  "metric_version": "real-input-human-v1",
  "definitions": {
    "header_coverage": "extracted on present / present labels",
    "header_exact": "canonical value exact / present labels",
    "header_conditional": "canonical value exact / extracted on present",
    "absent": "schema-valid abstentions / explicitly absent labels",
    "unannotated": "excluded, never interpreted as absent",
    "rows": "order-preserving DP; all four canonical cells exact; exclude entire partial tables",
    "line_precision": "TP / (TP + FP)",
    "line_recall": "TP / (TP + FN)",
    "line_f1": "2TP / (2TP + FP + FN); empty denominator null",
    "failures": "failed documents stay in annotated denominators; no absence credit",
    "evidence": "each human box center in same-page span; span text equals contained source tokens",
    "latency": "nearest-rank milliseconds, all attempts, metadata/extraction/schema",
    "slices": "any OCR attempted; completed embedded only; unknown failure; mutually exclusive"
  },
  "annotation_version": "human-invoice-v1",
  "corpus_fingerprint": "20adbcfa757d37ca3fc5df915d25ea0459c33e33f8752b2d407e6e665a6feaa9",
  "source_revision": "257e2662002b73f72e404c9e6e72abdcdbd946ba",
  "source_state": "working-tree changes",
  "extractor_version": "0.2.0",
  "pymupdf_version": "1.28.2",
  "ocr_available": true,
  "ocr_cli_version": "tesseract v5.5.3.20260724",
  "ocr_engine": "pymupdf-tesseract",
  "ocr_language": "eng",
  "ocr_dpi": 200,
  "minimum_meaningful_words": 8,
  "minimum_non_whitespace_characters": 40,
  "slices": {
    "all": {
      "attempted_documents": 29,
      "failed_documents": 0,
      "errors": {},
      "schema_validity": {
        "numerator": 29,
        "denominator": 29,
        "rate": 1.0
      },
      "known_page_documents": 29,
      "unknown_page_documents": 0,
      "total_known_pages": 29,
      "ocr_attempted_documents": 1,
      "ocr_completed_documents": 1,
      "ocr_failed_documents": 0,
      "ocr_completed_pages": 1,
      "input_types": {
        "pdf": 29,
        "png": 0,
        "jpeg": 0
      },
      "headers": {
        "invoice_number": {
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 28,
          "value_exact": 28,
          "supported_exact": 28,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "present_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "conditional_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 29,
            "denominator": 29,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          }
        },
        "invoice_date": {
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 28,
          "value_exact": 28,
          "supported_exact": 28,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "present_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "conditional_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 29,
            "denominator": 29,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          }
        },
        "currency": {
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 5,
          "value_exact": 5,
          "supported_exact": 5,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          },
          "present_exact_accuracy": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          },
          "conditional_exact_accuracy": {
            "numerator": 5,
            "denominator": 5,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 6,
            "denominator": 29,
            "rate": 0.20689655172413793
          },
          "supported_present_accuracy": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          }
        },
        "subtotal": {
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 29,
            "rate": 0.034482758620689655
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          }
        },
        "tax": {
          "present": 1,
          "absent": 1,
          "not_annotated": 27,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 2,
            "rate": 0.5
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          }
        },
        "total": {
          "present": 28,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 14,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 14,
            "denominator": 28,
            "rate": 0.5
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 14,
            "rate": 0.0
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 29,
            "rate": 0.034482758620689655
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          }
        }
      },
      "line_scored_documents": 29,
      "line_unannotated_documents": 0,
      "line_partial_documents": 0,
      "labelled_rows": 50,
      "predicted_rows": 22,
      "line_tp": 0,
      "line_fp": 22,
      "line_fn": 50,
      "line_precision": {
        "numerator": 0,
        "denominator": 22,
        "rate": 0.0
      },
      "line_recall": {
        "numerator": 0,
        "denominator": 50,
        "rate": 0.0
      },
      "line_f1": {
        "numerator": 0,
        "denominator": 72,
        "rate": 0.0
      },
      "exact_rows_with_supported_evidence": 0,
      "latency_documents": 29,
      "p50_latency_ms": 29.15670000948012,
      "p95_latency_ms": 74.42439999431372
    },
    "scan_or_ocr": {
      "attempted_documents": 1,
      "failed_documents": 0,
      "errors": {},
      "schema_validity": {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0
      },
      "known_page_documents": 1,
      "unknown_page_documents": 0,
      "total_known_pages": 1,
      "ocr_attempted_documents": 1,
      "ocr_completed_documents": 1,
      "ocr_failed_documents": 0,
      "ocr_completed_pages": 1,
      "input_types": {
        "pdf": 1,
        "png": 0,
        "jpeg": 0
      },
      "headers": {
        "invoice_number": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "invoice_date": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "currency": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "subtotal": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "tax": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "total": {
          "present": 0,
          "absent": 1,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 1,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "annotated_exact_accuracy": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        }
      },
      "line_scored_documents": 1,
      "line_unannotated_documents": 0,
      "line_partial_documents": 0,
      "labelled_rows": 0,
      "predicted_rows": 0,
      "line_tp": 0,
      "line_fp": 0,
      "line_fn": 0,
      "line_precision": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "line_recall": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "line_f1": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "exact_rows_with_supported_evidence": 0,
      "latency_documents": 1,
      "p50_latency_ms": 145.7211000379175,
      "p95_latency_ms": 145.7211000379175
    },
    "embedded_only": {
      "attempted_documents": 28,
      "failed_documents": 0,
      "errors": {},
      "schema_validity": {
        "numerator": 28,
        "denominator": 28,
        "rate": 1.0
      },
      "known_page_documents": 28,
      "unknown_page_documents": 0,
      "total_known_pages": 28,
      "ocr_attempted_documents": 0,
      "ocr_completed_documents": 0,
      "ocr_failed_documents": 0,
      "ocr_completed_pages": 0,
      "input_types": {
        "pdf": 28,
        "png": 0,
        "jpeg": 0
      },
      "headers": {
        "invoice_number": {
          "present": 28,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 28,
          "value_exact": 28,
          "supported_exact": 28,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "present_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "conditional_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          }
        },
        "invoice_date": {
          "present": 28,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 28,
          "value_exact": 28,
          "supported_exact": 28,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "present_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "conditional_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          },
          "supported_present_accuracy": {
            "numerator": 28,
            "denominator": 28,
            "rate": 1.0
          }
        },
        "currency": {
          "present": 28,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 5,
          "value_exact": 5,
          "supported_exact": 5,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          },
          "present_exact_accuracy": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          },
          "conditional_exact_accuracy": {
            "numerator": 5,
            "denominator": 5,
            "rate": 1.0
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          },
          "supported_present_accuracy": {
            "numerator": 5,
            "denominator": 28,
            "rate": 0.17857142857142858
          }
        },
        "subtotal": {
          "present": 28,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          }
        },
        "tax": {
          "present": 1,
          "absent": 0,
          "not_annotated": 27,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 1,
            "rate": 0.0
          }
        },
        "total": {
          "present": 28,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 14,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 14,
            "denominator": 28,
            "rate": 0.5
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 14,
            "rate": 0.0
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 28,
            "rate": 0.0
          }
        }
      },
      "line_scored_documents": 28,
      "line_unannotated_documents": 0,
      "line_partial_documents": 0,
      "labelled_rows": 50,
      "predicted_rows": 22,
      "line_tp": 0,
      "line_fp": 22,
      "line_fn": 50,
      "line_precision": {
        "numerator": 0,
        "denominator": 22,
        "rate": 0.0
      },
      "line_recall": {
        "numerator": 0,
        "denominator": 50,
        "rate": 0.0
      },
      "line_f1": {
        "numerator": 0,
        "denominator": 72,
        "rate": 0.0
      },
      "exact_rows_with_supported_evidence": 0,
      "latency_documents": 28,
      "p50_latency_ms": 28.792500030249357,
      "p95_latency_ms": 63.837300054728985
    },
    "unknown": {
      "attempted_documents": 0,
      "failed_documents": 0,
      "errors": {},
      "schema_validity": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "known_page_documents": 0,
      "unknown_page_documents": 0,
      "total_known_pages": 0,
      "ocr_attempted_documents": 0,
      "ocr_completed_documents": 0,
      "ocr_failed_documents": 0,
      "ocr_completed_pages": 0,
      "input_types": {
        "pdf": 0,
        "png": 0,
        "jpeg": 0
      },
      "headers": {
        "invoice_number": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "invoice_date": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "currency": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "subtotal": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "tax": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        },
        "total": {
          "present": 0,
          "absent": 0,
          "not_annotated": 0,
          "extracted_on_present": 0,
          "value_exact": 0,
          "supported_exact": 0,
          "absent_abstentions": 0,
          "false_extractions_on_absent": 0,
          "absent_failed_documents": 0,
          "coverage": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "present_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "conditional_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "absent_abstention_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "annotated_exact_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          },
          "supported_present_accuracy": {
            "numerator": 0,
            "denominator": 0,
            "rate": null
          }
        }
      },
      "line_scored_documents": 0,
      "line_unannotated_documents": 0,
      "line_partial_documents": 0,
      "labelled_rows": 0,
      "predicted_rows": 0,
      "line_tp": 0,
      "line_fp": 0,
      "line_fn": 0,
      "line_precision": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "line_recall": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "line_f1": {
        "numerator": 0,
        "denominator": 0,
        "rate": null
      },
      "exact_rows_with_supported_evidence": 0,
      "latency_documents": 0,
      "p50_latency_ms": null,
      "p95_latency_ms": null
    }
  }
}
```
