# Deterministic duplicate-risk evaluation

Synthetic/de-identified scenarios only; these results are not production fraud-detection claims.

- Scenario count: 25
- Policy version: `duplicate-risk-v1`
- Scenario set: `duplicate-risk-synthetic-v1`
- Source revision: `271cc5b277a6ee8f660eb4bee907c2b4c50ff1a4`
- Source-tree fingerprint: `ebbd5719a7c0168e5e8ea2d20ef4bbdfc76326c39155d74656ca0463db6329ca`
- Expected disposition accuracy: 1.0000
- Duplicate-signal precision: 1.0000
- Duplicate-signal recall: 1.0000
- Known-duplicate false-clear count: 0
- Clean-invoice false-review count: 0
- Incomplete-assessment accuracy: 1.0000
- Duplicate assessment count: 0
- p50 risk latency: 0.0390 ms
- p95 risk latency: 0.0805 ms

The engine emits explicit deterministic signals, not an opaque aggregate score. A review disposition neither rejects an invoice nor authorizes payment.
