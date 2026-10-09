# Reproducible deterministic evaluation

## Generated supporting-document identifier evaluation

The frozen `supporting-documents-v1-docker.json` report measured 30/30 synthetic PDF/PNG
documents and found 0/10 PO identifiers and 0/20 receipt/delivery PO references. The current
0.3.0 supporting extractor distinguishes explicit labels from bare identifiers and associates
values by page and visual-row geometry. `supporting-documents-v2-local.json` is the same known
dataset after the fix: 24/30 decoded locally, 8/8 PO identifiers and 16/16 references; six
images are `ocr_unavailable`. `supporting-unseen-v1-local.json` is a separate right/stacked-panel
family: 24/30 decoded locally, 8/8 plus 16/16 identifiers. These local measurements are not
30-document Docker OCR results. The new CI job runs both families with Tesseract, requires full
coverage, checks the known identifier regressions and `false_canonical_record_count == 0`, and
publishes aggregate-only reports. Replay latency and token usage are simulated; no live-model
quality or cost is claimed. Neither evaluator writes canonical PO or receipt records.

## Supporting-document case evaluation

The `supporting-documents-synthetic-v1` corpus contains 15 purchase orders and 15 goods receipts
across alternate labels, two-page token layouts, partial receiving, missing identifiers,
conflicting identifiers and embedded/OCR provenance. OCR-provenance examples exercise extraction
over OCR tokens but do not claim image OCR runtime accuracy. Header exact-match denominators are
the 15 examples for each document type. Exact line-item F1 uses multiset true-positive,
false-positive and false-negative counts across that type. Schema validity is valid typed outputs
over 15. Confirmation-required rate is proof outputs requiring confirmation over all 30.

```powershell
uv run python scripts/run_supporting_evaluation.py
Get-Content evals/reports/cases/supporting-documents-v1/report.md
```

CI must assert `false_canonical_record_count == 0`. The evaluator calls extraction rules directly
and never invokes canonical confirmation persistence.

The three-way suite contains 26 synthetic receipt/allocation scenarios and reports decision and
routing metrics, cumulative-overbilling detection, allocation correctness, idempotency,
serialized overbilling scenarios, latency and source-tree provenance. The offline suite does not
execute concurrent transactions; the PostgreSQL Compose test is the contention proof. Run
`uv run python scripts/run_three_way_evaluation.py`; its aggregate report is under
`evals/reports/matching/three-way-v1/`.

## Duplicate-risk evaluation

The `duplicate-risk-synthetic-v1` suite measures at least 25 synthetic scenarios independently of
FastAPI, SQLAlchemy, object storage and Celery. It reports disposition accuracy, duplicate-signal
precision/recall, false-clear and false-review counts, incomplete-data accuracy, duplicate
assessment count and p50/p95 deterministic latency. CI requires zero known-duplicate false clears
and zero duplicate assessments. Results are synthetic engineering evidence, not production fraud
detection claims. See [risk.md](risk.md).

The committed corpus is entirely synthetic. Generate it with:

```powershell
uv run python scripts/generate_synthetic_evaluation.py
```

Development evaluation is unguarded:

```powershell
uv run python -m invoiceops.evaluation --manifest evals/manifests/dev.jsonl --output-dir evals/reports/development
```

Holdout evaluation requires an explicit acknowledgement:

```powershell
uv run python -m invoiceops.evaluation --manifest evals/manifests/holdout.jsonl --output-dir evals/reports/holdout/0.2.0 --allow-holdout
```

Header coverage is `extracted / labeled`, conditional exact accuracy is
`correct / extracted`, and overall exact accuracy is `correct / labeled`.
Line items are aligned in reading order with dynamic programming before exact
item and field-level metrics are calculated. Every report records the exact
denominators and SHA-256 dataset fingerprint.

Reports contain normalized predictions and failure categories. They never
contain absolute paths, raw page text, evidence snippets, or stack traces.
Measured project results remain separate from external benchmark context.

## Review workflow scenarios

The committed `review-scenarios-v1` evaluation contains 17 synthetic allowed, invalid, stale,
unauthorized and repeated-request scenarios. Accuracy denominators are the scenarios in each named
category; expected-transition accuracy covers all 17. Three deterministic complete histories
measure event-chain verification and state reconstruction. `duplicate_case_count` measures repeated
logical-match insertion in the evaluation registry. `false_auto_resolution_count` counts rejected
scenarios that nevertheless returned a resolved state. Latency covers only pure in-process
transition logic, not HTTP or database time.

```powershell
uv run python scripts/run_review_evaluation.py
Get-Content evals/reports/review/review-v1/report.md
```

CI requires all category accuracies, event verification and reconstruction to equal 1.0, with zero
duplicate cases and zero false automatic resolutions.

## Hybrid replay and guarded live mode

The synthetic stress set covers unseen layouts, OCR/scanned and rotated sources, distracting
totals, duplicate quotes, missing fields, arithmetic inconsistency, embedded prompt injection,
multiple pages, and provider failure. Replay uses production routing, grounding, fusion, and
repository-owned schemas without network access:

```powershell
uv run python scripts/run_hybrid_evaluation.py --mode hybrid-replay `
  --output-dir evals/reports/hybrid/0.3.0-replay
```

The report separates 0.2.0 deterministic metrics from 0.3.0 replay metrics and includes header
exact accuracy, exact line F1, schema validity, coverage, grounding, agreement, disagreement
abstention, invocation/provider-failure rates, latency, and tokens. Cost stays `null` unless both
token prices are supplied. `hybrid-live` refuses to run without `--allow-live` and
organization-owned manifest wiring; it is excluded from ordinary tests and CI.

## Reproducible OCR runtime

An OCR-tagged manifest is rejected before document bytes are loaded unless the Tesseract runtime
passes its readiness check. Run the frozen holdout in the dedicated container:

```powershell
docker compose --profile evaluation run --rm evaluator `
  --manifest evals/manifests/holdout.jsonl `
  --output-dir evals/reports/synthetic/0.2.0-container `
  --allow-holdout
```

The container report records the Docker runtime, Tesseract version, `eng` language and 200 DPI.
It is separate from the earlier local environment-failure report, and its dataset fingerprint must
match the frozen holdout fingerprint.

## DocILE external benchmark

Install evaluation-only tools with `uv sync --group evaluation`. Download `annotated-trainval`
outside source control and set `DOCILE_DATASET_PATH` to that directory. Never store its token in
`.env`, commands, logs or Git.

Profile aggregate label and document counts without printing field text:

```powershell
uv run --group evaluation python scripts/profile_docile_dataset.py `
  --dataset-path $env:DOCILE_DATASET_PATH `
  --output work/docile-profile.json
```

Generate deterministic ID-only manifests after inspecting that profile:

```powershell
uv run --group evaluation python scripts/create_docile_samples.py `
  --dataset-path $env:DOCILE_DATASET_PATH
```

Run the 10-document smoke sample in both end-to-end and precomputed-OCR modes. The Compose
evaluator bind-mounts the directory in `DOCILE_DATASET_PATH` read-only and supplies Tesseract:

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  scripts/run_docile_evaluation.py `
  --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/smoke.json `
  --output-dir evals/reports/docile/0.2.0-smoke
```

Run this from the same PowerShell session in which `DOCILE_DATASET_PATH` points to the extracted
dataset. A direct Windows run deliberately fails its OCR-runtime preflight when Tesseract and its
English language data are unavailable.

Replace `smoke.json` with `benchmark.json` and the output directory with
`evals/reports/docile/0.2.0` for the fixed 100-document benchmark. The script invokes DocILE's
official `evaluate_dataset` implementation for KILE and LIR. Raw KILE/LIR prediction files remain
ignored. The committed report contains only aggregate supported-subset F1 and full official
F1/AP, with the two OCR modes kept separate.

### Aggregate failure analysis and targeted localization

The validation split contains 500 documents; the frozen benchmark selects 100.
The opt-in value-grounded extractor and aggregate comparison runner are documented in
[the failure analysis](docile-failure-analysis.md).
Both runners require a fresh explicit output directory. Never reuse the frozen 0.2.0 or
0.2.0-smoke directories; an existing directory is rejected before predictions are written.
The new analysis runner writes only aggregate reports and never exports source text or predictions.

### Invoice line-item coverage diagnosis

[The line-coverage analysis](invoice-line-coverage.md) separates header detection, visual rows,
row rejection and emission on the same fixed 500-document manifest in both OCR modes. Fresh
aggregate-only reports include official description/quantity TP, FP, FN, denominators and
precision/recall/F1. Header non-detection dominates; split headers are not established as the cause.

The opt-in two-column grammar at deterministic-line-coverage@0.4.0 adds one TP and one FP per
mode, leaving quantity unchanged and slightly reducing micro precision. Supported LIR F1 changes
from 4.085% to 4.139% end-to-end and 5.176% to 5.229% precomputed. This practical null result
does not justify promotion. All 500 validation documents are observed development data. The
frozen extractor, historical 100-document reports and production worker default are preserved.
