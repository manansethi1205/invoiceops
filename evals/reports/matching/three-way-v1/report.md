# Three-way matching evaluation

Synthetic/de-identified scenarios only; these are not production claims.

- Scenario count: 26
- Expected decision accuracy: 1.0000
- Expected reason recall: 1.0000
- Straight-through three-way match rate: 0.5385
- Needs-review rate: 0.4615
- False auto-match count: 0
- Allocation-on-review count: 0
- Allocation correctness rate: 1.0000
- Cumulative-overbilling detection rate: 1.0000
- Idempotency accuracy: 1.0000
- Serialized overbilling scenario accuracy: 1.0000
- p50 latency: 0.2304 ms
- p95 latency: 0.3122 ms
- Scenario fingerprint: `1038bb6dc168c74dd2d1419c1af231c21d75a0fb387809bce79eff137d7ed8da`
- Source-tree fingerprint: `2aaaad1b3b8ba60e0f165b21043d0e59458e110cefb852319ca74c7bd7c8fa0c`

A match result, duplicate-risk disposition, human resolution and payment authorization remain separate decisions.
The offline suite is sequential; PostgreSQL contention is tested in Compose.
