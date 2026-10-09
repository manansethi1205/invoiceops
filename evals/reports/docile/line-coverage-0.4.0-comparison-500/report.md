# Invoice line-item coverage: observed DocILE development split

All 500 validation documents are observed development data, not a fresh holdout.
Baseline and candidate consume identical source text when both are present.
Only aggregate counters and official location-based LIR metrics are exported.
No raw documents, source text, IDs, predictions or matchings are exported.
Stage attribution uses token-center containment; it is diagnostic, not official scoring.

| Mode | Variant | Field | TP | FP | FN | Pred | GT | Precision | Recall | F1 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| end_to_end | deterministic-baseline@0.2.0 | line_item_description | 30 | 39 | 1806 | 69 | 1836 | 43.4783% | 1.6340% | 3.1496% |
| end_to_end | deterministic-baseline@0.2.0 | line_item_quantity | 42 | 2 | 1534 | 44 | 1576 | 95.4545% | 2.6650% | 5.1852% |
| end_to_end | deterministic-baseline@0.2.0 | supported micro | 72 | 41 | 3340 | 113 | 3412 | 63.7168% | 2.1102% | 4.0851% |
| end_to_end | deterministic-line-coverage@0.4.0 | line_item_description | 31 | 40 | 1805 | 71 | 1836 | 43.6620% | 1.6885% | 3.2512% |
| end_to_end | deterministic-line-coverage@0.4.0 | line_item_quantity | 42 | 2 | 1534 | 44 | 1576 | 95.4545% | 2.6650% | 5.1852% |
| end_to_end | deterministic-line-coverage@0.4.0 | supported micro | 73 | 42 | 3339 | 115 | 3412 | 63.4783% | 2.1395% | 4.1395% |
| precomputed_ocr | deterministic-baseline@0.2.0 | line_item_description | 46 | 47 | 1790 | 93 | 1836 | 49.4624% | 2.5054% | 4.7693% |
| precomputed_ocr | deterministic-baseline@0.2.0 | line_item_quantity | 46 | 4 | 1530 | 50 | 1576 | 92.0000% | 2.9188% | 5.6581% |
| precomputed_ocr | deterministic-baseline@0.2.0 | supported micro | 92 | 51 | 3320 | 143 | 3412 | 64.3357% | 2.6964% | 5.1758% |
| precomputed_ocr | deterministic-line-coverage@0.4.0 | line_item_description | 47 | 48 | 1789 | 95 | 1836 | 49.4737% | 2.5599% | 4.8679% |
| precomputed_ocr | deterministic-line-coverage@0.4.0 | line_item_quantity | 46 | 4 | 1530 | 50 | 1576 | 92.0000% | 2.9188% | 5.6581% |
| precomputed_ocr | deterministic-line-coverage@0.4.0 | supported micro | 93 | 52 | 3319 | 145 | 3412 | 64.1379% | 2.7257% | 5.2291% |

## Stage counters

| Mode | Variant | Counter | Count |
|---|---|---|---:|
| end_to_end | deterministic-baseline | annotated_line_page_groups | 2543 |
| end_to_end | deterministic-baseline | documents | 500 |
| end_to_end | deterministic-baseline | documents_with_emitted_lines | 18 |
| end_to_end | deterministic-baseline | emitted_lines | 69 |
| end_to_end | deterministic-baseline | emitted_quantity_fields | 44 |
| end_to_end | deterministic-baseline | line_groups_multiple_visual_token_rows | 499 |
| end_to_end | deterministic-baseline | line_groups_no_visual_token_rows | 105 |
| end_to_end | deterministic-baseline | line_groups_numeric_cells_on_multiple_rows | 352 |
| end_to_end | deterministic-baseline | line_groups_one_visual_token_row | 1939 |
| end_to_end | deterministic-baseline | line_groups_stage_body_row_rejected | 142 |
| end_to_end | deterministic-baseline | line_groups_stage_header_not_detected_on_page | 2236 |
| end_to_end | deterministic-baseline | line_groups_stage_probable_item_row | 60 |
| end_to_end | deterministic-baseline | line_groups_stage_visual_tokens_missing | 105 |
| end_to_end | deterministic-baseline | pages | 635 |
| end_to_end | deterministic-baseline | pages_with_detected_header | 32 |
| end_to_end | deterministic-baseline | pages_with_words | 633 |
| end_to_end | deterministic-baseline | rows_before_header | 18578 |
| end_to_end | deterministic-baseline | rows_description_only | 169 |
| end_to_end | deterministic-baseline | rows_footer | 5 |
| end_to_end | deterministic-baseline | rows_header | 32 |
| end_to_end | deterministic-baseline | rows_ignored | 5 |
| end_to_end | deterministic-baseline | rows_missing_description | 101 |
| end_to_end | deterministic-baseline | rows_no_numeric_support | 166 |
| end_to_end | deterministic-baseline | rows_probable_item | 69 |
| end_to_end | deterministic-baseline | visual_rows | 19125 |
| end_to_end | deterministic-baseline | word_tokens | 163460 |
| end_to_end | deterministic-line-coverage | annotated_line_page_groups | 2543 |
| end_to_end | deterministic-line-coverage | documents | 500 |
| end_to_end | deterministic-line-coverage | documents_with_emitted_lines | 20 |
| end_to_end | deterministic-line-coverage | emitted_lines | 71 |
| end_to_end | deterministic-line-coverage | emitted_quantity_fields | 44 |
| end_to_end | deterministic-line-coverage | line_groups_multiple_visual_token_rows | 499 |
| end_to_end | deterministic-line-coverage | line_groups_no_visual_token_rows | 105 |
| end_to_end | deterministic-line-coverage | line_groups_numeric_cells_on_multiple_rows | 352 |
| end_to_end | deterministic-line-coverage | line_groups_one_visual_token_row | 1939 |
| end_to_end | deterministic-line-coverage | line_groups_stage_body_row_rejected | 145 |
| end_to_end | deterministic-line-coverage | line_groups_stage_header_not_detected_on_page | 2232 |
| end_to_end | deterministic-line-coverage | line_groups_stage_probable_item_row | 61 |
| end_to_end | deterministic-line-coverage | line_groups_stage_visual_tokens_missing | 105 |
| end_to_end | deterministic-line-coverage | pages | 635 |
| end_to_end | deterministic-line-coverage | pages_with_detected_header | 36 |
| end_to_end | deterministic-line-coverage | pages_with_words | 633 |
| end_to_end | deterministic-line-coverage | rows_before_header | 18518 |
| end_to_end | deterministic-line-coverage | rows_description_only | 197 |
| end_to_end | deterministic-line-coverage | rows_footer | 5 |
| end_to_end | deterministic-line-coverage | rows_header | 36 |
| end_to_end | deterministic-line-coverage | rows_ignored | 5 |
| end_to_end | deterministic-line-coverage | rows_missing_description | 120 |
| end_to_end | deterministic-line-coverage | rows_no_numeric_support | 173 |
| end_to_end | deterministic-line-coverage | rows_probable_item | 71 |
| end_to_end | deterministic-line-coverage | visual_rows | 19125 |
| end_to_end | deterministic-line-coverage | word_tokens | 163460 |
| precomputed_ocr | deterministic-baseline | annotated_line_page_groups | 2543 |
| precomputed_ocr | deterministic-baseline | documents | 500 |
| precomputed_ocr | deterministic-baseline | documents_with_emitted_lines | 22 |
| precomputed_ocr | deterministic-baseline | emitted_lines | 93 |
| precomputed_ocr | deterministic-baseline | emitted_quantity_fields | 50 |
| precomputed_ocr | deterministic-baseline | line_groups_multiple_visual_token_rows | 525 |
| precomputed_ocr | deterministic-baseline | line_groups_no_visual_token_rows | 5 |
| precomputed_ocr | deterministic-baseline | line_groups_numeric_cells_on_multiple_rows | 363 |
| precomputed_ocr | deterministic-baseline | line_groups_one_visual_token_row | 2013 |
| precomputed_ocr | deterministic-baseline | line_groups_stage_body_row_rejected | 127 |
| precomputed_ocr | deterministic-baseline | line_groups_stage_header_not_detected_on_page | 2328 |
| precomputed_ocr | deterministic-baseline | line_groups_stage_probable_item_row | 83 |
| precomputed_ocr | deterministic-baseline | line_groups_stage_visual_tokens_missing | 5 |
| precomputed_ocr | deterministic-baseline | pages | 635 |
| precomputed_ocr | deterministic-baseline | pages_with_detected_header | 36 |
| precomputed_ocr | deterministic-baseline | pages_with_words | 633 |
| precomputed_ocr | deterministic-baseline | rows_before_header | 18414 |
| precomputed_ocr | deterministic-baseline | rows_description_only | 169 |
| precomputed_ocr | deterministic-baseline | rows_footer | 5 |
| precomputed_ocr | deterministic-baseline | rows_header | 36 |
| precomputed_ocr | deterministic-baseline | rows_ignored | 11 |
| precomputed_ocr | deterministic-baseline | rows_missing_description | 62 |
| precomputed_ocr | deterministic-baseline | rows_no_numeric_support | 161 |
| precomputed_ocr | deterministic-baseline | rows_probable_item | 93 |
| precomputed_ocr | deterministic-baseline | visual_rows | 18951 |
| precomputed_ocr | deterministic-baseline | word_tokens | 149954 |
| precomputed_ocr | deterministic-line-coverage | annotated_line_page_groups | 2543 |
| precomputed_ocr | deterministic-line-coverage | documents | 500 |
| precomputed_ocr | deterministic-line-coverage | documents_with_emitted_lines | 24 |
| precomputed_ocr | deterministic-line-coverage | emitted_lines | 95 |
| precomputed_ocr | deterministic-line-coverage | emitted_quantity_fields | 50 |
| precomputed_ocr | deterministic-line-coverage | line_groups_multiple_visual_token_rows | 525 |
| precomputed_ocr | deterministic-line-coverage | line_groups_no_visual_token_rows | 5 |
| precomputed_ocr | deterministic-line-coverage | line_groups_numeric_cells_on_multiple_rows | 363 |
| precomputed_ocr | deterministic-line-coverage | line_groups_one_visual_token_row | 2013 |
| precomputed_ocr | deterministic-line-coverage | line_groups_stage_body_row_rejected | 136 |
| precomputed_ocr | deterministic-line-coverage | line_groups_stage_header_not_detected_on_page | 2318 |
| precomputed_ocr | deterministic-line-coverage | line_groups_stage_probable_item_row | 84 |
| precomputed_ocr | deterministic-line-coverage | line_groups_stage_visual_tokens_missing | 5 |
| precomputed_ocr | deterministic-line-coverage | pages | 635 |
| precomputed_ocr | deterministic-line-coverage | pages_with_detected_header | 42 |
| precomputed_ocr | deterministic-line-coverage | pages_with_words | 633 |
| precomputed_ocr | deterministic-line-coverage | rows_before_header | 18357 |
| precomputed_ocr | deterministic-line-coverage | rows_description_only | 202 |
| precomputed_ocr | deterministic-line-coverage | rows_footer | 7 |
| precomputed_ocr | deterministic-line-coverage | rows_header | 42 |
| precomputed_ocr | deterministic-line-coverage | rows_ignored | 11 |
| precomputed_ocr | deterministic-line-coverage | rows_missing_description | 67 |
| precomputed_ocr | deterministic-line-coverage | rows_no_numeric_support | 170 |
| precomputed_ocr | deterministic-line-coverage | rows_probable_item | 95 |
| precomputed_ocr | deterministic-line-coverage | visual_rows | 18951 |
| precomputed_ocr | deterministic-line-coverage | word_tokens | 149954 |

Header signatures and bounded alias probes are in report.json.
Multiple visual rows can reflect legitimate wrapping; they are not automatically errors.
Financial values are observed, never inferred. No production strategy is changed.
