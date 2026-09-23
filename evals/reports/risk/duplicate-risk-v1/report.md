# Deterministic duplicate-risk evaluation

Synthetic/de-identified scenarios only; these results are not production fraud-detection claims.

- Scenario count: 25
- Policy version: `duplicate-risk-v1`
- Scenario set: `duplicate-risk-synthetic-v1`
- Source revision: `b77e2c22a749f3b99237237432d943bf6cef3d48`
- Expected disposition accuracy: 1.0000
- Duplicate-signal precision: 1.0000
- Duplicate-signal recall: 1.0000
- Known-duplicate false-clear count: 0
- Clean-invoice false-review count: 0
- Incomplete-assessment accuracy: 1.0000
- Duplicate assessment count: 0
- p50 risk latency: 0.0260 ms
- p95 risk latency: 0.0423 ms

The engine emits explicit deterministic signals, not an opaque aggregate score. A review disposition neither rejects an invoice nor authorizes payment.
