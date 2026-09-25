# Delivery roadmap

The explainable three-way slice is implemented: immutable/idempotent receipts, append-only
reversals, reconciliation-safe allocation reuse, shared PO serialization, versioned context,
cumulative allocations, review/risk integration and evaluation.
ERP integration, payments, production authentication and generic anomaly models remain out of
scope.

Build this as independently measurable vertical slices. AI handles perception and ambiguity;
deterministic code handles arithmetic, policy, matching, and approval.

## 1. Durable ingestion — implemented

- Upload PDF/JPEG/PNG input with type, signature, size, and empty-file validation.
- Store bytes outside the database with a SHA-256 digest and metadata.
- Create and dispatch a durable idempotent job; expose its status.

## 2. Preprocessing and evidence contract — implemented

- Extract embedded PDF text and use Tesseract only below explicit quality thresholds.
- Normalize word coordinates and preserve OCR/embedded-text provenance.
- Define typed `EvidenceSpan` and `ExtractedField` contracts.

## 3. Deterministic extraction and evaluation — implemented

- Extract versioned header fields and line items with evidence-linked deterministic rules.
- Evaluate synthetic and DocILE data without committing private benchmark content.
- Preserve `deterministic-baseline@0.2.0` as the frozen comparison baseline.

## 4. Deterministic validation and matching — implemented

- Recompute financial relationships using Decimal arithmetic.
- Perform explainable two-way PO matching with a versioned policy and reason codes.
- Persist immutable match runs tied to a specific extraction run.

## 5. Evidence-grounded VLM fallback — implemented

- Route only insufficient deterministic outputs to an optional vision provider.
- Require strict candidate JSON and ground every accepted candidate against actual tokens.
- Abstain on grounded disagreement and preserve deterministic output on provider failure.
- Keep the provider disabled and model-less by default; replay evaluation is network-free.

## 6. Evidence-linked review and audit — implemented

- Open exactly one review case for each `NEEDS_REVIEW` match in the matching transaction.
- Enforce ownership, explicit resolution reasons and optimistic concurrency.
- Reconstruct state from versioned, structured-envelope hash chains and expose verification.
- Normalize indexed review triggers for scalable queue filtering and future risk signals.

## 7. Duplicate risk — implemented

- Persist one versioned, immutable duplicate-risk assessment per match and policy.
- Detect different-byte exact/reused/PO/near duplicate patterns with explicit evidence.
- Route risk signals through normalized review triggers without changing match decisions.
- Treat missing comparison features explicitly and gate behavior with stored policy.

## 8. Three-way matching — implemented

- Persist immutable receipts and append-only reversals under shared PO-level locking.
- Match against received quantities and reconcile one reusable allocation per invoice.
- Preserve fingerprinted receiving context and route changed allocations to review.

## 9. Broader risk and approval policy — planned

- Detect altered bank details and other calibrated anomaly signals after measured error analysis.
- Keep payment authorization outside model and risk-engine authority.
- Model company-specific escalation and approval evidence as deterministic policy.

## 10. Observability and deployment — observability implemented, deployment planned

- Export privacy-bounded OpenTelemetry traces and metrics to local Tempo and Prometheus.
- Provision an InvoiceOps operations dashboard and demonstration SLOs in Grafana.
- Add MLflow only when experiment lineage becomes a measured requirement.
- Add Terraform for one real cloud path using S3, SQS, RDS, and a container service.
- Publish measured service and business metrics separately from external benchmarks.
