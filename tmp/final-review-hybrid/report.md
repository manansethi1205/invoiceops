# Hybrid replay evaluation

Synthetic/de-identified stress cases only; no live provider was called.

- Dataset: `synthetic-hybrid-stress-v1` (12 examples)
- Extractor: `hybrid-routed@0.3.0`
- Prompt: `invoice-vision-v1`
- Source revision: `99f3598b355ff6fb538aebfdc83975c5bd059b3e`

| Metric | Deterministic 0.2.0 | Hybrid replay 0.3.0 |
| --- | ---: | ---: |
| Schema valid | 1.0000 | 1.0000 |
| Header coverage | 0.8889 | 0.9306 |
| Critical coverage | 0.8333 | 0.8958 |
| Exact line-item F1 | 1.0000 | 1.0000 |

## Header exact match

| Field | Deterministic 0.2.0 | Hybrid replay 0.3.0 |
| --- | ---: | ---: |
| invoice_number | 0.5833 | 0.7500 |
| invoice_date | 0.9167 | 1.0000 |
| currency | 0.9167 | 1.0000 |
| subtotal | 1.0000 | 1.0000 |
| tax | 1.0000 | 1.0000 |
| total | 0.8333 | 0.8333 |

- Grounded candidate rate: 0.8889
- Deterministic/VLM agreement rate: 0.3333
- Disagreement abstention rate: 1.0000
- Fallback invocation rate: 0.9167
- Provider failure rate: 0.0909
- p50/p95 total latency: 13.00/13.00 ms
- p50/p95 provider latency: 12.00/12.00 ms
- Mean input/output/total tokens per document: 83.33/16.67/100.00
- Estimated cost: null

Safety assertions: no_ungrounded_candidate_promoted=true, all_grounded_disagreements_abstained=true, schema_valid_rate_is_one=true, matching_input_remains_canonical_invoice=true

Confidence is uncalibrated diagnostic metadata and never authorizes matching or payment.
