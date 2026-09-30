# Supporting-document synthetic evaluation

- Dataset: `supporting-documents-synthetic-v1`
- Documents: 30 (15 purchase orders, 15 goods receipts)
- Inputs are synthetic token layouts, including six OCR-provenance examples; this is not a claim
  about image OCR runtime accuracy.

| Metric | Purchase order | Goods receipt |
| --- | ---: | ---: |
| Primary identifier exact match | 1.0000 | 1.0000 |
| Referenced/date exact match | 1.0000 | 1.0000 |
| Line-item F1 | 1.0000 | 1.0000 |
| Schema-valid rate | 1.0000 | 1.0000 |

- Confirmation-required rate: 1.0000
- False canonical record count: 0
- p50/p95 extraction latency: 2.043 / 4.390 ms

The safety invariant is `false_canonical_record_count == 0`. Extraction evaluation never invokes
the confirmation service and therefore cannot create canonical PO or receipt records.
