# Delivery roadmap

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
- Reconstruct state from append-only hash-chained events and expose verification.

## 7. Risk and approval policy — planned

- Add duplicate, bank-detail-change, and calibrated amount-anomaly signals.
- Model company-specific escalation and approval evidence as deterministic policy.

## 8. Observability and deployment — planned

- Add MLflow lineage, OpenTelemetry, Prometheus, and Grafana.
- Add Terraform for one real cloud path using S3, SQS, RDS, and a container service.
- Publish measured service and business metrics separately from external benchmarks.
