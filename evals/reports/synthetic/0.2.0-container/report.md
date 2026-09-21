# InvoiceOps deterministic extraction evaluation

- Extractor: `deterministic-baseline@0.2.0`
- Split: `holdout`
- Examples: 15
- Dataset fingerprint: `b5e921c971b57914a2c59efd2195a624bb8521e5f39bb61740ad9f225a1fa3a3`
- Evaluation runtime: `docker`
- OCR engine: `tesseract`
- OCR language: `eng`
- OCR DPI: 200
- OCR version: `tesseract 5.5.0`

## Header fields

| Field | Labeled | Extracted | Correct | Coverage | Conditional exact | Overall exact |
|---|---:|---:|---:|---:|---:|---:|
| invoice_number | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |
| invoice_date | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |
| currency | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |
| subtotal | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |
| tax | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |
| total | 14 | 14 | 14 | 100.00% | 100.00% | 100.00% |

## Line items

- Exact item F1: 100.00%
- Field-level micro F1: 100.00%
- Ground-truth/predicted items: 28/28

| Field | Labeled | Correct | Accuracy |
|---|---:|---:|---:|
| description | 28 | 28 | 100.00% |
| quantity | 27 | 27 | 100.00% |
| unit_price | 27 | 27 | 100.00% |
| line_total | 28 | 28 | 100.00% |

## Operational

- Schema validity: 100.00%
- Failures: 0
- OCR document rate: 13.33%
- Average pages (15 known): 1.13
- Latency p50/p95/max (ms): 7.217 / 561.683 / 561.683

## Tagged slices

| Slice | Documents | Schema validity | Exact item F1 |
|---|---:|---:|---:|
| layout=adversarial | 2 | 100.00% | 100.00% |
| layout=aliases | 2 | 100.00% | 100.00% |
| layout=missing_cells | 2 | 100.00% | 100.00% |
| layout=multipage | 2 | 100.00% | 100.00% |
| layout=negative | 1 | 100.00% | n/a |
| layout=ocr | 2 | 100.00% | 100.00% |
| layout=standard | 2 | 100.00% | 100.00% |
| layout=wrapped | 2 | 100.00% | 100.00% |
| pages=multiple | 2 | 100.00% | 100.00% |
| pages=single | 13 | 100.00% | 100.00% |
| source=digital | 13 | 100.00% | 100.00% |
| source=ocr | 2 | 100.00% | 100.00% |

These are measured project results on synthetic data, not external benchmarks.
