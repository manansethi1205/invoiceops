# DocILE aggregate failure analysis and targeted fix

Validation split loaded: 500 documents.
Both variants use the same fixed manifest and the same text/OCR per document.
This is a development comparison on an external benchmark, not a held-out production claim.
The candidate changes only header evidence locations; values, statuses and line items are preserved.
Official metrics use the installed DocILE evaluator. Geometric overlap counts are diagnostic only.
Raw documents, OCR, source text, predictions, matchings and document IDs are not exported.

| Mode | Variant | Documents | Supported KILE F1 | Supported LIR F1 |
|---|---|---:|---:|---:|
| end_to_end | deterministic-baseline@0.2.0 | 100 | 0.0000% | 18.4896% |
| end_to_end | deterministic-value-grounded@0.3.0 | 100 | 10.6024% | 18.4896% |
| precomputed_ocr | deterministic-baseline@0.2.0 | 100 | 0.0000% | 22.2791% |
| precomputed_ocr | deterministic-value-grounded@0.3.0 | 100 | 13.3017% | 22.2791% |

## Per-field counts

| Mode | Variant | Field | TP | FP | FN | F1 |
|---|---|---|---:|---:|---:|---:|
| end_to_end | deterministic-baseline | amount_total_gross | 0 | 42 | 108 | 0.0000% |
| end_to_end | deterministic-baseline | amount_total_net | 0 | 4 | 20 | 0.0000% |
| end_to_end | deterministic-baseline | amount_total_tax | 0 | 2 | 15 | 0.0000% |
| end_to_end | deterministic-baseline | date_issue | 0 | 1 | 98 | 0.0000% |
| end_to_end | deterministic-baseline | document_id | 0 | 23 | 102 | 0.0000% |
| end_to_end | deterministic-baseline | line_item_description | 29 | 22 | 309 | 14.9100% |
| end_to_end | deterministic-baseline | line_item_quantity | 42 | 2 | 293 | 22.1636% |
| end_to_end | deterministic-value-grounded | amount_total_gross | 16 | 26 | 92 | 21.3333% |
| end_to_end | deterministic-value-grounded | amount_total_net | 1 | 3 | 19 | 8.3333% |
| end_to_end | deterministic-value-grounded | amount_total_tax | 0 | 2 | 15 | 0.0000% |
| end_to_end | deterministic-value-grounded | date_issue | 1 | 0 | 97 | 2.0202% |
| end_to_end | deterministic-value-grounded | document_id | 4 | 19 | 98 | 6.4000% |
| end_to_end | deterministic-value-grounded | line_item_description | 29 | 22 | 309 | 14.9100% |
| end_to_end | deterministic-value-grounded | line_item_quantity | 42 | 2 | 293 | 22.1636% |
| precomputed_ocr | deterministic-baseline | amount_total_gross | 0 | 40 | 108 | 0.0000% |
| precomputed_ocr | deterministic-baseline | amount_total_net | 0 | 7 | 20 | 0.0000% |
| precomputed_ocr | deterministic-baseline | amount_total_tax | 0 | 2 | 15 | 0.0000% |
| precomputed_ocr | deterministic-baseline | date_issue | 0 | 1 | 98 | 0.0000% |
| precomputed_ocr | deterministic-baseline | document_id | 0 | 28 | 102 | 0.0000% |
| precomputed_ocr | deterministic-baseline | line_item_description | 41 | 17 | 297 | 20.7071% |
| precomputed_ocr | deterministic-baseline | line_item_quantity | 46 | 4 | 289 | 23.8961% |
| precomputed_ocr | deterministic-value-grounded | amount_total_gross | 21 | 19 | 87 | 28.3784% |
| precomputed_ocr | deterministic-value-grounded | amount_total_net | 3 | 4 | 17 | 22.2222% |
| precomputed_ocr | deterministic-value-grounded | amount_total_tax | 0 | 2 | 15 | 0.0000% |
| precomputed_ocr | deterministic-value-grounded | date_issue | 1 | 0 | 97 | 2.0202% |
| precomputed_ocr | deterministic-value-grounded | document_id | 3 | 25 | 99 | 4.6154% |
| precomputed_ocr | deterministic-value-grounded | line_item_description | 41 | 17 | 297 | 20.7071% |
| precomputed_ocr | deterministic-value-grounded | line_item_quantity | 46 | 4 | 289 | 23.8961% |

Detailed status, overlap, document-type and changed-evidence counts are in report.json.
Remaining missing/ambiguous values and incorrect semantic mappings are not repaired by localization.
The default production extractor and frozen 100-document reports remain unchanged.
