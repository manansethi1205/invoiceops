# InvoiceOps deterministic extraction evaluation

- Extractor: `deterministic-baseline@0.2.0`
- Split: `development`
- Examples: 25
- Dataset fingerprint: `0c59d7f39b5e0db5d4431e2db74a08d2af061b62ddf8f86e1ddb194dd38ee607`

## Header fields

| Field | Labeled | Extracted | Correct | Coverage | Conditional exact | Overall exact |
|---|---:|---:|---:|---:|---:|---:|
| invoice_number | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |
| invoice_date | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |
| currency | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |
| subtotal | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |
| tax | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |
| total | 23 | 20 | 20 | 86.96% | 100.00% | 86.96% |

## Line items

- Exact item F1: 93.02%
- Field-level micro F1: 92.90%
- Ground-truth/predicted items: 46/40

| Field | Labeled | Correct | Accuracy |
|---|---:|---:|---:|
| description | 46 | 40 | 86.96% |
| quantity | 44 | 38 | 86.36% |
| unit_price | 45 | 39 | 86.67% |
| line_total | 46 | 40 | 86.96% |

## Operational

- Schema validity: 88.00%
- Failures: 3
- OCR document rate: 12.00%
- Average pages (22 known): 1.14
- Latency p50/p95/max (ms): 7.423 / 376.596 / 401.798

## Tagged slices

| Slice | Documents | Schema validity | Exact item F1 |
|---|---:|---:|---:|
| layout=adversarial | 3 | 100.00% | 100.00% |
| layout=aliases | 4 | 100.00% | 100.00% |
| layout=missing_cells | 3 | 100.00% | 100.00% |
| layout=multipage | 3 | 100.00% | 100.00% |
| layout=negative | 2 | 100.00% | n/a |
| layout=ocr | 3 | 0.00% | n/a |
| layout=standard | 4 | 100.00% | 100.00% |
| layout=wrapped | 3 | 100.00% | 100.00% |
| pages=multiple | 3 | 100.00% | 100.00% |
| pages=single | 22 | 86.36% | 91.89% |
| source=digital | 22 | 100.00% | 100.00% |
| source=ocr | 3 | 0.00% | n/a |

These are measured project results on synthetic data, not external benchmarks.
