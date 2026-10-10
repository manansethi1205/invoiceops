# Qualitative paired DocILE header-miss audit

Observed development data; no independent holdout or causal accuracy claim.

**The equal-stratum sample is nonrepresentative and was reviewed by one person.**

**The 40 miss pairs mean at least one mode missed**, not that both modes missed. 4 pairs were detected end-to-end but missed in precomputed OCR; 4 were detected in precomputed OCR but missed end-to-end.

| Mode | Selected groups | Detected headers | Actual header misses | Uncertainty among actual misses |
|---|---:|---:|---:|---|
| end_to_end | 48 | 12 | 36 | 12/36 |
| precomputed_ocr | 48 | 12 | 36 | 15/36 |

The category table below uses all selected groups; its /48 denominator is not the denominator for uncertainty among header misses.

- seed: 1205
- universe_paired_groups: 2543
- selected_pairs: 48
- selected_documents: 45
- selected_miss_pairs: 40
- selected_control_pairs: 8
- jointly_reviewed_pair_denominator: 48

| Mode | Category | Count | Selected denominator |
|---|---|---:|---:|
| end_to_end | annotation_or_coordinate_mismatch | 0 | 48 |
| end_to_end | continuation_page | 0 | 48 |
| end_to_end | detected_header_verified | 12 | 48 |
| end_to_end | document_not_invoice | 12 | 48 |
| end_to_end | geometry_or_row_grouping | 3 | 48 |
| end_to_end | other_or_uncertain | 12 | 48 |
| end_to_end | tokens_absent | 7 | 48 |
| end_to_end | wording_not_supported | 2 | 48 |
| end_to_end | inspected | 48 | 48 |
| end_to_end | unreviewed | 0 | 48 |
| end_to_end | uncertainty_count | 12 | 48 |
| precomputed_ocr | annotation_or_coordinate_mismatch | 0 | 48 |
| precomputed_ocr | continuation_page | 0 | 48 |
| precomputed_ocr | detected_header_verified | 12 | 48 |
| precomputed_ocr | document_not_invoice | 12 | 48 |
| precomputed_ocr | geometry_or_row_grouping | 0 | 48 |
| precomputed_ocr | other_or_uncertain | 15 | 48 |
| precomputed_ocr | tokens_absent | 4 | 48 |
| precomputed_ocr | wording_not_supported | 5 | 48 |
| precomputed_ocr | inspected | 48 | 48 |
| precomputed_ocr | unreviewed | 0 | 48 |
| precomputed_ocr | uncertainty_count | 15 | 48 |

Aggregate strata, paired comparisons and limitations are in report.json.
