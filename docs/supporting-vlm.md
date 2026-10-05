# Routed vision fallback for supporting documents

The worker always saves `deterministic-supporting-documents@0.3.0` first. A separate
`supporting-hybrid-routed@0.4.0` run is created only when a typed routing reason exists and
`SUPPORTING_VLM_ENABLED=true`. The default is **false**. Enabling invoice `VLM_ENABLED` does not
enable supporting-document calls, or vice versa. `DELIVERY_NOTE` has a distinct candidate class
and prompt version but maps to the same current confirmation semantics as goods receipts.

The currently supported reasons are required-field missing/ambiguous, no or incomplete table
lines, conflicting PO header totals, unassociated receipt quantities, and OCR use around a missing
required field. A complete deterministic extraction is returned without rendering pages or
calling a provider. PO, receipt, and delivery-note prompts have independent versions
(`supporting-po-vision-v1`, `supporting-receipt-vision-v1`, and
`supporting-delivery-vision-v1`).

To opt in locally, set `SUPPORTING_VLM_ENABLED=true`, `SUPPORTING_VLM_PROVIDER=openai`,
`SUPPORTING_VLM_MODEL` to a model available to your account, and `OPENAI_API_KEY` in the untracked
`.env`. This transmits rendered page images to the selected provider. Obtain document-owner
authorization and review provider retention and data-processing terms before using real files.
The adapter uses the [Responses structured-output API](https://developers.openai.com/api/docs/guides/structured-outputs)
and [base64 image inputs](https://developers.openai.com/api/docs/guides/images-vision).
CI and unit tests use only fake/replay providers and synthetic documents. Never put credentials,
real invoices, raw model responses, OCR text, or page images in Git. The model request disables
provider-side response storage with `store=False`, but that is not a blanket data-retention
guarantee; review the provider's current terms.

Each candidate has a proposed string value, zero-based page, verbatim evidence quote, and optional
confidence. Grounding requires the page to exist, a unique exact token quote, and a normalized
value supported by the quote. Header amounts additionally require a nearby subtotal/tax/total
label and its first adjacent number. Line quantities and prices must occupy a matching table
column, and candidate line fields must share a visual row. Confidence cannot bypass these checks.
When a grounded proposal conflicts with a reliable deterministic value, the hybrid field becomes
`ambiguous` with evidence from both candidates; the original baseline output and the model's
candidate remain separately preserved. Unsupported candidates leave the deterministic value
unchanged. Rendering errors, malformed responses, provider refusal, timeout, or outage are
recorded with a bounded failure code; the deterministic extraction stays confirmable.

`supporting_model_calls` stores role, provider/model, prompt version, document SHA-256, typed route
reasons, sanitized parsed candidates, grounding/fusion codes, usage, latency, and failure code.
It has a foreign key to the supporting run, not the invoice-only `extraction_runs` table. A
unique run/prompt/fingerprint constraint prevents duplicate rows on redelivery. Logs and metric
labels contain codes and document identifiers only, never extracted text. The application-level
database audit does not prevent a database administrator from altering data.

The API prefers a successful current-version hybrid run, then a successful current-version
deterministic run, then current failures, then historical runs. An older hybrid run cannot eclipse
a newer baseline. Historical and confirmed runs remain immutable. Neither
run creates a purchase order or goods receipt. A reviewer must explicitly submit a confirmation
against a specific extraction run and case version before any canonical supporting record exists.
Matching, arithmetic, approval, and payment authorization remain deterministic; confirmation
does not authorize payment. OIDC mode uses verified identity; development headers are accepted
only in explicit non-production development mode.

## Replay evaluation

Run:

```powershell
uv run python scripts/run_supporting_hybrid_evaluation.py --output evals/reports/supporting-hybrid-v3.json
uv run python scripts/run_supporting_document_holdout.py --output evals/reports/supporting-documents-v2-local.json
uv run python scripts/run_supporting_document_holdout.py --unseen --output evals/reports/supporting-unseen-v1-local.json
uv run pytest -q tests/evaluation/test_supporting_hybrid_evaluation.py
```

For the full image-OCR holdout, use the Tesseract-equipped evaluation image and write a separate
environment-specific report (do not overwrite the local one):

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator scripts/run_supporting_document_holdout.py --output evals/reports/supporting-documents-v2-docker.json
docker compose --profile evaluation run --rm --entrypoint python evaluator scripts/run_supporting_document_holdout.py --unseen --output evals/reports/supporting-unseen-v1-docker.json
```

If a large Python wheel times out while building the image, the Dockerfile now allows 180 seconds
per `uv` HTTP request. On a particularly slow connection, build once with a higher timeout,
then run the already-built evaluator (Compose `run` has no `--no-build` option):

```powershell
docker compose --profile evaluation build --build-arg UV_HTTP_TIMEOUT=300 evaluator
docker compose --profile evaluation run --rm --entrypoint python evaluator scripts/run_supporting_document_holdout.py --output evals/reports/supporting-documents-v2-docker.json
```

For a local what-if cost estimate, supply both `--input-cost-per-million` and
`--output-cost-per-million`; no default model price is assumed or committed.

The committed `supporting-hybrid-v1.json` is the frozen **before** report. Never overwrite it.
The v2 report is the PO-row before/after comparison; v3 reruns the same six fixed token-layout examples across PO,
receipt, and delivery-note roles, including a grounded conflict. The runner compares per-role identifier/date/
currency exact match and exact line-item precision/recall/F1. Grounded acceptance uses submitted
non-null candidate fields as denominator and counts only fills/agreements; conflict rate uses
grounded candidates. Abstention uses routed documents. Latency combines measured local processing
with explicitly synthetic replay provider latency. `confirmation_rate` is null because no humans
participate; `confirmation_required_rate` is one by design. `false_canonical_record_count` is
zero because the runner has no database write path. Each role/mode has p50/p95 latency; the
overall latency is hybrid replay. Cost is null unless explicit per-million-token prices are
supplied (deterministic cost is zero). These numbers are not production accuracy, latency, or
cost claims.

The committed v1 Docker report is the **before** document-level result: 30/30 decoded, but
PO identifiers 0/10 and receipt/delivery PO references 0/20. The local v2 report has 24/30
decoded, with 8/8 PO identifiers and 16/16 receipt/delivery references; six PNGs lack local
Tesseract and remain explicit failures. The separate untuned right/stacked-panel family also
has 24/30 local coverage and 8/8 plus 16/16 identifier exact match. The CI evaluator will
measure both full OCR sets and require complete processing, known-case identifier regressions
and zero canonical records. It does not require a flattering F1 on the new family.

The `supporting-generated-documents-v1` generator fixes 45 PDF/PNG documents: 9 train, 6
development and 30 holdout (10 per role). The fingerprint covers each generated byte stream,
role, split, family and truth. Historical 0.1.0 PO rows and header rules, current 0.3.0
deterministic extraction and hybrid replay
are evaluated on identical successfully decoded documents. Header exact-match denominators are
decoded documents per role. Line precision uses predicted complete rows and recall uses labeled
rows. Routing uses decoded documents; grounded acceptance uses proposed non-null fields;
abstention uses routed documents; conflict uses grounded candidates. Unprocessed images are
reported separately and excluded from accuracy denominators. On hosts without Tesseract, six
PNG holdout cases are `ocr_unavailable`, not assigned surrogate predictions. Replay token usage
and provider latency are simulated; no live-model cost or quality is claimed.

## Known limitations

- The frozen set is intentionally small and does not represent vendor layout diversity. Its
  historical PO line F1 is zero; the revised unified row parser fixes this printed-number defect.
- The historical PDF/PNG report exposed PO identifier and receipt PO-reference failures. The
  new explicit-label visual-row path repairs these on locally decoded PDFs; full image-OCR
  behavior must be checked by the container evaluator.
- Exact token grounding abstains when OCR disagrees with visible image text or a quote repeats.
- PostgreSQL row locking serializes concurrent calls for the same invocation. A worker crash
  after the provider has processed a request but before its outcome commits can still cause a
  retry to spend again; the database cannot guarantee exactly-once external billing.
- Provider errors fall back to the baseline and are not automatically retried within the same
  fingerprint. A deliberate new hybrid extractor version (and prompt/model version when changed)
  is needed for re-evaluation.
