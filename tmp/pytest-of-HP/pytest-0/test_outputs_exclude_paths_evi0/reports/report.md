# InvoiceOps deterministic extraction evaluation

- Extractor: `deterministic-baseline@0.2.0`
- Split: `development`
- Examples: 1
- Dataset fingerprint: `92f805333450c84bec4c634122a11b7d1123a0c17d4b023620b5199cbba1ce32`
- Evaluation runtime: `local`
- OCR engine: `tesseract`
- OCR language: `eng`
- OCR DPI: 200
- OCR version: `unavailable`

## Header fields

| Field | Labeled | Extracted | Correct | Coverage | Conditional exact | Overall exact |
|---|---:|---:|---:|---:|---:|---:|
| invoice_number | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |
| invoice_date | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |
| currency | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |
| subtotal | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |
| tax | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |
| total | 1 | 1 | 1 | 100.00% | 100.00% | 100.00% |

## Line items

- Exact item F1: 100.00%
- Field-level micro F1: 100.00%
- Ground-truth/predicted items: 2/2

| Field | Labeled | Correct | Accuracy |
|---|---:|---:|---:|
| description | 2 | 2 | 100.00% |
| quantity | 2 | 2 | 100.00% |
| unit_price | 2 | 2 | 100.00% |
| line_total | 2 | 2 | 100.00% |

## Operational

- Schema validity: 100.00%
- Failures: 0
- OCR document rate: 0.00%
- Average pages (1 known): 1.00
- Latency p50/p95/max (ms): 6.004 / 6.004 / 6.004

## Tagged slices

| Slice | Documents | Schema validity | Exact item F1 |
|---|---:|---:|---:|
| layout=standard | 1 | 100.00% | 100.00% |
| source=digital | 1 | 100.00% | 100.00% |

These are measured project results on synthetic data, not external benchmarks.
