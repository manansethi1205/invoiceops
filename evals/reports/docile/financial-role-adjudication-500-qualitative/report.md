# Invoice-focused financial-role adjudication

500-document observed development data; nonrepresentative qualitative sample, not holdout.

Review provenance: **same_reviewer_blinded_repeat**, source **assistant**.

Same-reviewer repeat is not independent inter-rater reliability; label blinding cannot erase source familiarity.

Fixed seed **2110**; seed-ranked round-robin joint strata; unresolved first; fresh groups exclude first-audit documents. **37 pairs from 33 documents**, capped at 2 groups per document across all tiers; the same groups are reviewed in both modes.

| Selection tier | Requested | Achieved | Eligible | Shortfall | Cap exclusions encountered |
|---|---:|---:|---:|---:|---:|
| prior_unresolved | 15 | 15 | 15 | 0 | 0 |
| fresh_misses | 12 | 12 | 1134 | 0 | 0 |
| ocr_disagreements | 6 | 6 | 12 | 0 | 2 |
| detected_controls | 4 | 4 | 81 | 0 | 0 |

Invoice-stratum universe: 1516 groups; 1027 other-stratum groups excluded. Fresh tiers exclude all 48 first-audit groups and their 45 documents (289 invoice-stratum groups). Cap exclusions count candidates encountered, not an exhaustive excluded population. The first 48-pair audit and all frozen line-coverage reports are unchanged.

| Mode | Selected | Header misses | Adjudicated | Unresolved | Primary / any pass disagreements, each / both inspected |
|---|---:|---:|---:|---:|---|
| end_to_end | 37 | 33 | 37 | 3 | 0/37 / 1/37 |
| precomputed_ocr | 37 | 27 | 37 | 3 | 0/37 / 1/37 |

Unresolved among actual header misses: **end_to_end: 3/33**; **precomputed_ocr: 3/27**. Unresolved primary evidence is separate from unknown/competing financial roles.

DocILE invoice stratum is not visual confirmation.

| Mode | Visually invoice | Not invoice | Unknown | Genuine item table | Summary | List | None | Unknown table | Denominator |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| end_to_end | 34 | 1 | 2 | 29 | 6 | 2 | 0 | 0 | 37 |
| precomputed_ocr | 34 | 1 | 2 | 29 | 6 | 2 | 0 | 0 | 37 |

| Mode | Primary barrier | Count | Adjudicated denominator |
|---|---|---:|---:|
| end_to_end | token_loss | 7 | 37 |
| end_to_end | unsupported_labels | 1 | 37 |
| end_to_end | geometry | 3 | 37 |
| end_to_end | ambiguous_financial_roles | 13 | 37 |
| end_to_end | no_item_table | 7 | 37 |
| end_to_end | not_visually_invoice | 1 | 37 |
| end_to_end | clear_roles | 2 | 37 |
| end_to_end | unresolved | 3 | 37 |
| precomputed_ocr | token_loss | 0 | 37 |
| precomputed_ocr | unsupported_labels | 1 | 37 |
| precomputed_ocr | geometry | 1 | 37 |
| precomputed_ocr | ambiguous_financial_roles | 17 | 37 |
| precomputed_ocr | no_item_table | 7 | 37 |
| precomputed_ocr | not_visually_invoice | 1 | 37 |
| precomputed_ocr | clear_roles | 7 | 37 |
| precomputed_ocr | unresolved | 3 | 37 |

The decision gate uses **visually confirmed invoice misses**, excluding detected controls and unconfirmed document types.

| Mode | Primary barrier | Count | Invoice-miss denominator |
|---|---|---:|---:|
| end_to_end | token_loss | 7 | 30 |
| end_to_end | unsupported_labels | 1 | 30 |
| end_to_end | geometry | 3 | 30 |
| end_to_end | ambiguous_financial_roles | 11 | 30 |
| end_to_end | no_item_table | 7 | 30 |
| end_to_end | unresolved | 1 | 30 |
| precomputed_ocr | unsupported_labels | 1 | 24 |
| precomputed_ocr | geometry | 1 | 24 |
| precomputed_ocr | ambiguous_financial_roles | 14 | 24 |
| precomputed_ocr | no_item_table | 7 | 24 |
| precomputed_ocr | unresolved | 1 | 24 |

| Mode | Printed role | Present | Absent | Unknown | Competing | Denominator |
|---|---|---:|---:|---:|---:|---:|
| end_to_end | description | 36 | 0 | 1 | 0 | 37 |
| end_to_end | quantity | 14 | 19 | 1 | 3 | 37 |
| end_to_end | unit_price | 11 | 12 | 12 | 2 | 37 |
| end_to_end | printed_line_total | 17 | 10 | 2 | 8 | 37 |
| precomputed_ocr | description | 36 | 0 | 1 | 0 | 37 |
| precomputed_ocr | quantity | 14 | 19 | 1 | 3 | 37 |
| precomputed_ocr | unit_price | 11 | 12 | 12 | 2 | 37 |
| precomputed_ocr | printed_line_total | 17 | 10 | 2 | 8 | 37 |

| Mode | Amount context signal | Count | Adjudicated denominator |
|---|---|---:|---:|
| end_to_end | printed_net | 5 | 37 |
| end_to_end | printed_tax | 7 | 37 |
| end_to_end | printed_gross | 5 | 37 |
| end_to_end | summary_total | 33 | 37 |
| end_to_end | competing | 10 | 37 |
| end_to_end | unknown | 18 | 37 |
| end_to_end | none | 0 | 37 |
| precomputed_ocr | printed_net | 5 | 37 |
| precomputed_ocr | printed_tax | 7 | 37 |
| precomputed_ocr | printed_gross | 5 | 37 |
| precomputed_ocr | summary_total | 33 | 37 |
| precomputed_ocr | competing | 10 | 37 |
| precomputed_ocr | unknown | 18 | 37 |
| precomputed_ocr | none | 0 | 37 |

Amount signals are multilabel; their counts do not sum to the denominator. They identify printed context, not inferred monetary values.

end_to_end: unknown/competing financial role in 24/37; competing primary explanations in 2/37.

precomputed_ocr: unknown/competing financial role in 24/37; competing primary explanations in 1/37.


Paired primary changes: 9/37.

Header detection transitions (end-to-end -> precomputed; 0=miss, 1=detected): 0->0: 27/37; 0->1: 6/37; 1->1: 4/37.

Paired printed-role classification changes: description: 0/37; quantity: 0/37; unit_price: 0/37; printed_line_total: 0/37.

Explicit adjudication: confirmed_agreement: 66/74; resolved_disagreement: 2/74; retained_uncertainty: 6/74.

| Supported dominant category | Potential next implementation |
|---|---|
| token_loss | bounded OCR/preprocessing experiment |
| unsupported_labels | versioned parser experiment after explicit-role confirmation |
| geometry | versioned deterministic layout experiment after repeated-layout confirmation |
| ambiguous_financial_roles | guarded vision/human-review pilot preserving abstention |
| no_item_table | explicit no-item-table abstention and review handoff |
| not_visually_invoice | document-scope gate before invoice extraction |
| clear_roles | no failure-directed implementation justified |
| unresolved | no-go: evidence does not support an implementation category |

Gate: complete adjudication; at least eight and strict majority of visually confirmed invoice misses in each mode; modes agree; layout/label pattern still needs explicit repetition evidence.

**Choice: no-go: evidence does not support an implementation category.**

- DocILE invoice stratum is not visual invoice confirmation.
- Nonrepresentative, equal-stratum qualitative selection; observed development data.
- Same-reviewer repeat is not independent inter-rater reliability.
- Assistant repeat review does not establish independent human adjudication.
- No arithmetic or annotation-only inference of financial roles.
- Correlated OCR modes and groups are not independent observations.
- Printed-role judgments concern page/table context, not annotation-row field accuracy.
- Source familiarity and memory can survive label blinding.
- Category majority does not establish a repeated explicit parser pattern.
- Unadjudicated and unknown evidence is unresolved, not a confirmed cause.

No extractor or official metric changes; this is not a coverage gain. The host Tesseract smoke limitation is not a commit blocker: actual audit OCR preparation ran in the guarded evaluator container.
