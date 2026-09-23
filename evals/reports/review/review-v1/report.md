# Review workflow evaluation

Synthetic scenario set: `review-scenarios-v1`  
Workflow version: `review-v1`  
Scenario count: 17

| Metric | Result |
| --- | ---: |
| Expected transition accuracy | 1.0000 |
| Allowed transition accuracy | 1.0000 |
| Invalid transition rejection rate | 1.0000 |
| Stale-version rejection accuracy | 1.0000 |
| Unauthorized-owner action rejection rate | 1.0000 |
| Idempotent replay rejection accuracy | 1.0000 |
| Duplicate case count | 0 |
| Event-chain verification rate | 1.0000 |
| State reconstruction accuracy | 1.0000 |
| False automatic resolution count | 0 |
| p50 transition latency (ms) | 0.004200 |
| p95 transition latency (ms) | 0.006700 |
| Maximum transition latency (ms) | 0.013000 |

All scenarios are synthetic state-machine checks. Latency measures in-process transition logic,
not database or HTTP performance. Chain and reconstruction rates cover three complete synthetic
histories; duplicate-case count covers repeated insertion into a logical-match registry.
`ACCEPTED_EXCEPTION` records a review outcome and never authorizes payment.
