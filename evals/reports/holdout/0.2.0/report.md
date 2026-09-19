# InvoiceOps deterministic extraction evaluation

- Extractor: `deterministic-baseline@0.2.0`
- Split: `holdout`
- Examples: 15
- Dataset fingerprint: `b5e921c971b57914a2c59efd2195a624bb8521e5f39bb61740ad9f225a1fa3a3`

## Header fields

| Field | Labeled | Extracted | Correct | Coverage | Conditional exact | Overall exact |
|---|---:|---:|---:|---:|---:|---:|
| invoice_number | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |
| invoice_date | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |
| currency | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |
| subtotal | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |
| tax | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |
| total | 14 | 12 | 12 | 85.71% | 100.00% | 85.71% |

## Line items

- Exact item F1: 92.31%
- Field-level micro F1: 92.16%
- Ground-truth/predicted items: 28/24

| Field | Labeled | Correct | Accuracy |
|---|---:|---:|---:|
| description | 28 | 24 | 85.71% |
| quantity | 27 | 23 | 85.19% |
| unit_price | 27 | 23 | 85.19% |
| line_total | 28 | 24 | 85.71% |

## Operational

- Schema validity: 86.67%
- Failures: 2
- OCR document rate: 13.33%
- Average pages (13 known): 1.15
- Latency p50/p95/max (ms): 7.003 / 488.831 / 488.831

## Tagged slices

| Slice | Documents | Schema validity | Exact item F1 |
|---|---:|---:|---:|
| layout=adversarial | 2 | 100.00% | 100.00% |
| layout=aliases | 2 | 100.00% | 100.00% |
| layout=missing_cells | 2 | 100.00% | 100.00% |
| layout=multipage | 2 | 100.00% | 100.00% |
| layout=negative | 1 | 100.00% | n/a |
| layout=ocr | 2 | 0.00% | n/a |
| layout=standard | 2 | 100.00% | 100.00% |
| layout=wrapped | 2 | 100.00% | 100.00% |
| pages=multiple | 2 | 100.00% | 100.00% |
| pages=single | 13 | 84.62% | 90.91% |
| source=digital | 13 | 100.00% | 100.00% |
| source=ocr | 2 | 0.00% | n/a |

These are measured project results on synthetic data, not external benchmarks.
