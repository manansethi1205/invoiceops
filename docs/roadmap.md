# Delivery roadmap

Build this as independently measurable vertical slices. Do not introduce a model until the
document and evidence contracts exist.

## 1. Durable ingestion — implemented

- Upload a PDF/JPEG/PNG and reject empty, oversized, or signature-mismatched content.
- Store bytes outside the database and record a SHA-256 digest plus metadata.
- Create and dispatch a durable job; expose its status.

Exit evidence: API tests, migration validation, queue state transition, and a Compose smoke test.

## 2. Preprocessing and evidence contract

- Render PDF pages with PyMuPDF; normalize orientation and contrast with OpenCV.
- Define normalized page coordinates and typed `EvidenceSpan` / `ExtractedField` schemas.
- Store page derivatives and preprocessing lineage.

Exit evidence: adversarial fixtures for corrupt, encrypted, rotated, oversized, and mixed-page
documents; deterministic rendering tests.

## 3. OCR and schema-constrained extraction

- Add one OCR engine and one hosted vision-language model behind provider interfaces.
- Extract vendor, invoice number/date, currency, taxes, totals, and line items.
- Require every value to carry page/box evidence and model/prompt/version lineage.
- Abstain when schema or evidence constraints fail.

Exit evidence: schema validity, field exact match, line-item F1, calibration, abstention quality,
latency, and cost per invoice on synthetic/de-identified data plus DocILE and a stress set.

## 4. Deterministic validation and matching

- Recompute subtotal, tax, and grand total using decimal arithmetic.
- Implement configurable two-way/three-way matching at header and line-item level.
- Represent zero-tolerance custom purchases and agreement-specific percentage/absolute tolerances
as versioned policy—not model prompts.
- Route threshold approvals, mismatches, disputes, and exceptional cases with reason codes.

Exit evidence: exhaustive policy boundary tests and explainable match outcomes.

## 5. Risk, review, and audit

- Add exact/fuzzy duplicate signals, vendor bank-detail-change controls, and calibrated amount
anomaly signals.
- Build evidence-linked human review and append-only audit events.
- Require the PO, order confirmation, advance evidence, and email approval when policy calls for
them.

Exit evidence: false-auto-clear rate, straight-through rate, touches per invoice, review time, and
complete decision reconstruction.

## 6. Evaluation, observability, and deployment

- Version corrections into an evaluation set; keep training opt-in and leakage-safe.
- Track experiments and lineage in MLflow; instrument OpenTelemetry, Prometheus, and Grafana.
- Add Terraform for one real cloud path using S3, SQS, RDS, and a container service.

Exit evidence: reproducible evaluation runs, service SLOs, failure drills, cost dashboard, and a
deployed synthetic demo. External benchmarks must remain visually separate from measured results.
