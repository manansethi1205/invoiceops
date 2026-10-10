# Reproducible deterministic evaluation

## Invoice hybrid value-binding safety replay

`hybrid-routed@0.4.0` requires a unique source-token value subspan inside each located quote.
The [fresh offline report](../evals/reports/hybrid/0.4.0-replay/report.md) runs the same 12 synthetic
documents as 0.3.0, with no live model calls. Header coverage remains 67/72, critical coverage
43/48 and line-item F1 1.0; all safety assertions pass. These are synthetic regression results,
not DocILE improvement or live-model performance. Adversarial unit tests exercise quote/value
mismatches that the historical 12-document replay does not cover. Historical reports are frozen;
the replay writer now refuses existing output directories. See [the grounding boundary and
row-association boundary](hybrid-extraction.md).

## Invoice row association safety

`hybrid-routed@0.5.0` adds source-evidence association before any line-cell fusion and an
`invoice-v2` extraction issue that forces deterministic review under `matching-v3` and
`three-way-v3`. See [the association rules and limitations](hybrid-extraction.md).
The [network-free replay](../evals/reports/hybrid/0.5.0-replay/report.md) and separate
[synthetic row stress corpus](../evals/reports/hybrid/0.5.0-row-alignment/report.md) are fresh reports.
Neither changes the frozen 0.4.0 report. Association precision is 20/20, coverage 20/29;
9/29 candidate rows abstain. In 15 complete-invoice trials, eight carry unresolved row issues and
nine need review; all nine independently expected review cases avoid automatic matches. In the
30 removed-quantity trials, all 20 promotions are correct. These synthetic results do not claim
population precision. Stress denominators include candidate rows for association,
missing quantity cells for promotions, and invoices for review/false automatic matches.
Historical matching reports retain their original policy version; replaying current matching code
uses the new policy version. No live model or payment-authority change is involved.

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
precision/recall/F1. A group on a page with no detected header is an observed stage, not a diagnosed cause;
continuation pages need not print repeated headers.

The opt-in two-column grammar at deterministic-line-coverage@0.4.0 adds one TP and one FP per
mode, leaving quantity unchanged and slightly reducing micro precision. Supported LIR F1 changes
from 4.085% to 4.139% end-to-end and 5.176% to 5.229% precomputed. This practical null result
does not justify promotion. All 500 validation documents are observed development data. The
frozen extractor, historical 100-document reports and production worker default are preserved.

### Qualitative paired header-miss audit

The evaluation-only [header-miss audit](invoice-line-coverage.md#evaluation-only-paired-header-miss-audit)
selects roughly 40 missed groups and 8 detected controls with fixed-seed joint stratification
and a combined per-document cap. The same groups are inspected in both OCR modes. Observable
signals remain separate from manually assigned explanations, and uninspected cases remain
unreviewed. Continuation pages and page-local line IDs are explicitly tested.

Source pages, token text, IDs, annotations, paths and case labels remain in guarded private
scratch or tmpfs. Fresh public outputs contain only allowlisted aggregate counts, denominators,
paired comparisons, sampling method and uncertainty. This is qualitative analysis of observed
development data; it changes neither extraction nor official scoring and does not justify
promoting the opt-in line-coverage candidate.


The completed [500-document qualitative header audit](invoice-line-coverage.md#reviewed-aggregate-result)
selected 40 miss pairs plus eight controls from 45 documents (seed 1205, two-group document cap).
All 96 mode observations were inspected privately. The 40 miss pairs mean at least one mode
missed; four were detected in each mode but missed in the other. Each mode has 36 actual misses:
uncertainty among misses is 12/36 end-to-end and 15/36 precomputed (12/48 and 15/48 among all
selected reviews), with header disagreement on 8/48 paired groups.
No continuation-without-header or coordinate-mismatch cause was confirmed in this sample.
Mixed categories and unresolved financial roles motivated the completed bounded invoice-focused
adjudication below. Aggregate counts and denominators are published
in a fresh report directory; case assets and labels remain ignored and private. Frozen evaluation
reports, extractor versions and production selection are unchanged. No official evaluator rerun
is required because its inputs and metric computation are unchanged.

### Invoice-focused financial-role adjudication

`invoiceops/evaluation/financial_role_audit.py` and
`scripts/adjudicate_docile_financial_roles.py` implement the private two-pass workflow and strict
aggregate export. The [completed adjudication](invoice-line-coverage.md#invoice-focused-financial-role-adjudication)
and [standalone report](../evals/reports/docile/financial-role-adjudication-500-qualitative/report.md)
record all requested/achieved counts, exclusions, caps, denominators, printed roles, amount
context, paired-mode changes, disagreement, uncertainty and the final implementation gate.

Preparation requires the frozen 500-document private inventory and fixed validation manifest.
Seed-ranked joint-stratum selection first includes unresolved invoice-stratum groups, then fresh
misses, OCR disagreements and controls. Fresh groups exclude every first-audit document; a
combined cap is never relaxed to meet requested counts. DocILE's document-type label is a
sampling stratum; visual invoice status is reviewed separately. Source-visible roles cannot be
inferred from arithmetic, annotation labels or another mode's tokens. Unknown and competing
explanations remain valid outcomes. The private rubric distinguishes item tables, summary/list
layouts, missing or competing roles, printed net/tax/gross context, token loss, labels and geometry.
Role judgments concern source-visible page/table context, not a selected annotation row's field
accuracy; repeated groups on a page do not add independent evidence.

Use `prepare` to create a fresh private root and pass-one source/token assets. Complete its
anonymous `reviews.json`, then `seal --pass-number 1`; `second-pass` verifies that seal and
creates a different anonymous order without prior labels. Complete and seal pass two before
`adjudication-template` reveals the private comparison. Inspect and explicitly fill every
adjudication as confirmed agreement, resolved disagreement or retained uncertainty; the exporter
rejects agreement that conceals classification differences. `export` requires both intact seals
and a fresh aggregate output directory. Reviewer source/provenance are declared explicitly;
assistant review cannot claim two independent reviewers. No additional model endpoint is called.

Private input/output must be ignored and untracked guarded scratch or the existing dedicated
container tmpfs; paths outside those roots, links/junctions and existing outputs are refused.
Nested input files and copied review assets are checked for links as well. Case-level free text,
IDs, paths, source content and labels never enter routine logs or public reports. Export accepts
a fixed schema, fixed prose, categorical allowlists and nonnegative integer counts; it validates
mode, role, category, adjudication and paired denominators. Public JSON/Markdown are aggregate
only. First-audit reports, private labels and historical 100/500-document measurements are frozen.

The achieved sample is 37 paired groups from 33 documents (15 prior unresolved, 12 fresh misses,
six disagreements, four controls; seed 2110, document cap two). Actual misses are 33 end-to-end
and 27 precomputed; unresolved primary evidence is 3/33 and 3/27 among those misses. One assistant
performed a blinded repeat, not independent human adjudication: primary disagreement 0/37 and
any-classification disagreement 1/37 per mode. All 74 observations were explicitly adjudicated.
Financial-role ambiguity leads among visually confirmed invoice misses at 11/30 and 14/24 but
fails the predeclared shared majority gate. **No-go for a new extraction implementation from
this sample**; retain current abstention and production selection. This is observed development
data, not representative prevalence, independent holdout, causal proof or a measured extraction
improvement. The actual audit OCR preparation ran in the guarded evaluator container; the
documented host Tesseract smoke limitation is not a commit blocker. Official evaluator inputs
and metric computation are unchanged, so no full official rerun was required.


CI report directories must be fresh: the hybrid and row-association writers create their own
output directories and reject existing ones. CI must not pre-create those leaf directories.
A CLI regression test runs the same replay command successfully once, then verifies that a
second invocation fails without changing the first report. The row-association stress corpus
also runs in CI with precision, cross-row promotion, automatic-match and review-accounting gates.
Generated OpenAPI JSON and TypeScript contracts must be regenerated after schema changes.


Local CI preflight for the uncommitted row-safety slice passed: Python suite 572 passed,
two Windows symlink-permission skips and nine Docker/private-data tests deselected; the targeted
replay/association suite passed 44 tests. Ruff, mypy (125 files), offline lockfile validation,
repository hygiene and UTF-8 checks passed. All eight offline evaluation steps and their exact
CI assertions passed. Generated OpenAPI JSON and TypeScript types reproduce.

With isolated synthetic configuration and no live-model credentials, PostgreSQL 16 migrations
passed, both generated PDF/PNG holdouts evaluated 30/30 documents with all CI gates passing,
Docker integration passed four tests in default mode and five in fake-hybrid mode, and the
telemetry smoke test passed. The skipped Docker cases are conditional on those separate modes.
Web typecheck, lint, 28 unit tests, production build, 20 browser/accessibility/visual tests,
Docker web build and authenticated login/proxy smoke checks passed. Restricted Windows process
execution initially timed out starting Vitest workers; the unchanged default suite passed when
run outside that process sandbox. No test assertions or report overwrite protections were relaxed.
These local checks do not guarantee GitHub runner/network availability. Historical reports remain
frozen, and no commit or push was performed.
