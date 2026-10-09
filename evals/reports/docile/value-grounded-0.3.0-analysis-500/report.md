# DocILE aggregate failure analysis and targeted fix

Validation split loaded: 500 documents.
Both variants use the same fixed manifest and the same text/OCR per document.
This is a development comparison on an external benchmark, not a held-out production claim.
The candidate changes only header evidence locations; values, statuses and line items are preserved.
Official metrics use the installed DocILE evaluator. Geometric overlap counts are diagnostic only.
Raw documents, OCR, source text, predictions, matchings and document IDs are not exported.

| Mode | Variant | Documents | Supported KILE F1 | Supported LIR F1 |
|---|---|---:|---:|---:|
| end_to_end | deterministic-baseline@0.2.0 | 500 | 0.0000% | 4.0851% |
| end_to_end | deterministic-value-grounded@0.3.0 | 500 | 12.2302% | 4.0851% |
| precomputed_ocr | deterministic-baseline@0.2.0 | 500 | 0.0000% | 5.1758% |
| precomputed_ocr | deterministic-value-grounded@0.3.0 | 500 | 14.3804% | 5.1758% |

## Per-field counts

| Mode | Variant | Field | TP | FP | FN | F1 |
|---|---|---|---:|---:|---:|---:|
| end_to_end | deterministic-baseline | amount_total_gross | 0 | 201 | 519 | 0.0000% |
| end_to_end | deterministic-baseline | amount_total_net | 0 | 23 | 68 | 0.0000% |
| end_to_end | deterministic-baseline | amount_total_tax | 0 | 2 | 45 | 0.0000% |
| end_to_end | deterministic-baseline | date_issue | 0 | 6 | 512 | 0.0000% |
| end_to_end | deterministic-baseline | document_id | 0 | 117 | 453 | 0.0000% |
| end_to_end | deterministic-baseline | line_item_description | 30 | 39 | 1806 | 3.1496% |
| end_to_end | deterministic-baseline | line_item_quantity | 42 | 2 | 1534 | 5.1852% |
| end_to_end | deterministic-value-grounded | amount_total_gross | 90 | 111 | 429 | 25.0000% |
| end_to_end | deterministic-value-grounded | amount_total_net | 7 | 16 | 61 | 15.3846% |
| end_to_end | deterministic-value-grounded | amount_total_tax | 0 | 2 | 45 | 0.0000% |
| end_to_end | deterministic-value-grounded | date_issue | 6 | 0 | 506 | 2.3166% |
| end_to_end | deterministic-value-grounded | document_id | 16 | 101 | 437 | 5.6140% |
| end_to_end | deterministic-value-grounded | line_item_description | 30 | 39 | 1806 | 3.1496% |
| end_to_end | deterministic-value-grounded | line_item_quantity | 42 | 2 | 1534 | 5.1852% |
| precomputed_ocr | deterministic-baseline | amount_total_gross | 0 | 195 | 519 | 0.0000% |
| precomputed_ocr | deterministic-baseline | amount_total_net | 0 | 22 | 68 | 0.0000% |
| precomputed_ocr | deterministic-baseline | amount_total_tax | 0 | 3 | 45 | 0.0000% |
| precomputed_ocr | deterministic-baseline | date_issue | 0 | 7 | 512 | 0.0000% |
| precomputed_ocr | deterministic-baseline | document_id | 0 | 137 | 453 | 0.0000% |
| precomputed_ocr | deterministic-baseline | line_item_description | 46 | 47 | 1790 | 4.7693% |
| precomputed_ocr | deterministic-baseline | line_item_quantity | 46 | 4 | 1530 | 5.6581% |
| precomputed_ocr | deterministic-value-grounded | amount_total_gross | 107 | 88 | 412 | 29.9720% |
| precomputed_ocr | deterministic-value-grounded | amount_total_net | 11 | 11 | 57 | 24.4444% |
| precomputed_ocr | deterministic-value-grounded | amount_total_tax | 1 | 2 | 44 | 4.1667% |
| precomputed_ocr | deterministic-value-grounded | date_issue | 7 | 0 | 505 | 2.6975% |
| precomputed_ocr | deterministic-value-grounded | document_id | 15 | 122 | 438 | 5.0847% |
| precomputed_ocr | deterministic-value-grounded | line_item_description | 46 | 47 | 1790 | 4.7693% |
| precomputed_ocr | deterministic-value-grounded | line_item_quantity | 46 | 4 | 1530 | 5.6581% |

Detailed status, overlap, document-type and changed-evidence counts are in report.json.
Remaining missing/ambiguous values and incorrect semantic mappings are not repaired by localization.
The default production extractor and frozen 100-document reports remain unchanged.
