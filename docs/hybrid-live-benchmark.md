# Guarded synthetic live-provider benchmark

This extends `scripts/run_hybrid_evaluation.py --mode hybrid-live`; it is evaluation only.
Implementation and ordinary tests make no live calls. Production provider settings, routing,
extractor versions, matching, review, canonical records and payment authority are unchanged.
The frozen 0.5.0 replay and 15-case row stress reports remain synthetic safety regressions,
not measurements of live-model accuracy.

## Corpus and source labels

The generator produces 16 invoices, 32 labelled item rows and 17 pages from a seed. Eight
development documents use grid, explicit financial-role, missing-column and summary layouts.
Eight reserved documents use reordered financial columns/rows, stacked headers, ambiguous amount
columns and scanned quantity-first layouts. One table continues onto a second page without a
header; two inputs are PNGs requiring OCR. Each family has distinct-amount and repeated-amount
variants. Description, quantity, unit price, printed net line total, tax, gross, summary and unknown
amount cells have page-coordinate labels. Missing and ambiguous values remain null: neither the
model nor evaluator is given permission to infer an absent invoice value from arithmetic.

The in-memory synthetic PO fixture is independently generated from the generator's quantities
and prices. It is never persisted as a canonical record. Financial-role and review errors are
checked against labels and truth, not just the issue flag emitted by fusion. A grounded value
from an unknown/gross/summary column can be wrong even when its number is correct or arithmetic
passes. The evaluator reports such false financial promotions and false automatic matches.

Only a fresh directory below ignored `work/hybrid-live-synthetic/` may hold corpus assets and its
labelled manifest. The runner regenerates the entire inventory and verifies every document byte
before any upload. Manifest declarations or hashes alone do not establish synthetic origin.
Symlinks/junctions, tracked scratch assets, changed bytes, changed labels and other manifests are
rejected. Generate and evaluate with the same locked PyMuPDF environment; a byte mismatch across
environments fails closed. No real or DocILE document can be substituted through this interface.

```powershell
uv run python scripts/run_hybrid_evaluation.py --mode generate-synthetic `
  --seed 20261011 --corpus-dir work/hybrid-live-synthetic/corpus-20261011
```

This command is network-free once dependencies are installed. It refuses an existing directory.
Reserved layout families are separated by construction, not a statistical business holdout.
After inspecting their evaluation outcomes they are observed development data. Fake-provider tests
of their safety machinery do not establish live-model performance or independent generalization.

## Local manifest regression: no network or model

`hybrid-replay` still evaluates the separate 12-case `synthetic-hybrid-stress-v1` corpus;
it does not read the generated 16-invoice manifest. Internally, the manifest evaluator already
supported injected fake clients in tests, but there was no offline CLI for this corpus.
`synthetic-local` now uses the same corpus verification, routing, deterministic extraction,
grounding, fusion, matching safety scoring and aggregate denominators through a shared evaluator.
The public live entry point retains its authorization check and existing budget/provider guards.

This local mode constructs only an in-process, fixed `label-guided-stub-v1` fixture provider.
It never reads credentials, initializes a provider SDK/HTTP client or verifies live prices.
Candidates copy known printed cell labels, with missing/unknown roles left null; no arithmetic
fills absent values. This is a label-guided oracle regression, not a model-quality measurement.
Requests/successful responses in its aggregate metrics count local fixture invocations. No
external provider is called: API tokens and cost are zero, and price assumptions are null.
Local latency is pipeline/fixture execution time, not provider inference latency.

Use this single-line command from the repository root with installed dependencies. It does not
use a package installer and needs no API key, model, spending limit or `--allow-live`:

```powershell
.\.venv\Scripts\python.exe scripts/run_hybrid_evaluation.py --mode synthetic-local --manifest work/hybrid-live-synthetic/corpus-20261011-run2/manifest.json --max-documents 16 --max-pages 17 --partition all --allow-holdout --local-source-mode synthetic-scan-tokens --output-dir evals/reports/hybrid/16-invoice-synthetic-local-01
```

The explicit `synthetic-scan-tokens` option substitutes labelled token fixtures only for the two
generated PNGs; the 14 PDFs retain native embedded-text extraction. The report states this input
mode, counts two `synthetic_scan_documents` and zero actual `ocr_documents`. This does not measure
Tesseract or OCR quality and cannot be compared directly with a native-OCR live run. Omit the
option (or select `native`) to use actual local OCR, which fails closed if Tesseract is unavailable.
Neither input option permits a real provider. Live/model/billing options are rejected in local mode;
the fixture-token option is rejected in every other CLI mode.

The full partition has 16 documents, 17 pages and 32 labelled rows. Development and reserved
families each have 8 documents/16 rows. Both extraction modes use identical text inputs, and all
cases retain their denominators, including abstentions. `--allow-holdout` acknowledges inspection
of reserved layouts; it does not authorize live inference. Once inspected, these layouts are
observed development data. Source labels available to the stub preclude accuracy/generalization
claims for its hybrid results.

Corpus assets must remain byte-identical to the generated seed inventory in ignored scratch;
tampered assets/labels, real documents, unsafe output paths and existing output directories are
refused. Pick a new output leaf for each run; frozen replay reports are not changed. Network-free
CLI regressions forbid socket connections, HTTP/SDK construction, live settings and live pricing,
and check the supplied manifest fingerprint/seed, all partition denominators and zero billed usage.

## Spending admission and verified prices

The [native-OCR milestone](hybrid-native-ocr-milestone.md) compares actual OCR with the scan-token
reference on the same verified corpus, without model calls. New reports include per-input-type
counts and OCR runtime/backend version provenance. Reports lacking `metric_version` load as
unknown; only fresh generation explicitly stamps the current scorer version.

The original local report's four false automatic matches were traced to center-only source-role
scoring of label-plus-value header evidence. The evaluation-only `synthetic-source-safety-v2`
correction retains competing-role rejection and all matching decisions. See the
[aggregate diagnosis and denominator comparison](hybrid-local-diagnosis.md). Frozen reports are
not rewritten; the correction is identified in fresh reports by `metric_version`.

No live run is authorized by the implementation task. Before a real run, obtain explicit user
authorization, an exact model choice, credential setup and a USD spending limit. The only currently
verified model is `gpt-4.1-mini-2025-04-14`; aliases and other models fail closed. The
`openai-standard-2026-10-11` snapshot was checked against the official
[model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini): USD 0.40 input
and 1.60 output per million tokens, 1,047,576 context tokens and 32,768 maximum output tokens.
The official [vision guide](https://developers.openai.com/api/docs/guides/images-vision) documents
an image-token multiplier of 1.62 for this snapshot. The price snapshot expires after seven days;
reverify and explicitly update the evaluation profile before later runs. Confirmation means these
standard token rates apply to the selected account; custom or regional billing is not supported.

Before each request, the ledger reserves
`(ceil(context_tokens * 1.62) * input_rate + max_output_tokens * output_rate) / 1,000,000`.
This intentionally overbounds image, prompt and schema charges rather than estimating image
tokens. With 4,096 output tokens, the reservation is USD **0.6853832** per request; a smaller
spending limit is rejected before any call. Valid known usage releases excess reservation while
retaining a conservative input-image multiplier allowance. A failure with unknown billing,
missing/inconsistent/out-of-range usage, or an unexpected returned model/tier keeps the whole
reservation and halts further calls. Budget refusal happens before a request is sent.

The evaluation adapter pins the OpenAI endpoint, disables proxies and redirects, disables SDK and
application retries, supplies no tools, uses `store=false`, and requests the default service tier,
disabled truncation and an explicit output limit. See the official
[Responses API controls](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
The bound assumes the provider honors those verified request/model/billing contracts. It governs
this process's standard USD token charges, not account-wide billing, taxes, currency conversion,
concurrent processes or future price changes. Do not represent a dashboard soft budget or a
post-call estimate as this admission bound. A new invocation has a new ledger; do not retry a
charged/interrupted run without reviewing its spending and obtaining authorization again.
Verbose SDK/HTTP logging and `OPENAI_LOG` are refused before initialization: the installed SDK's
debug request-options log can include image payloads. Initialization errors are sanitized too.

The separate usage estimate uses observed input/output usage and uncached prices, so cached
inputs may make it conservative. It is not a billing invoice. If any request's usage is unknown,
the total estimate is null; known-usage cost and the retained charge upper bound are still shown.
SDK parse failures can obscure usage; the reservation covers them and stops further calls.

## Authorized command template; do not execute without approval

Configure the key privately as `OPENAI_API_KEY`; never put it in the command, manifest or report.
Production `VLM_ENABLED` can remain false. Generate assets and run in the same environment with
a working Tesseract English runtime. Full-corpus OCR readiness, extraction and rendering are
checked before spending anything; an OCR failure is a refusal, not a reduced corpus. Use the
existing evaluation container if the host OCR runtime is unavailable, with the working repository
(including Git metadata) and writable ignored scratch/report mounts available to the runner.

Choose and explicitly authorize the model and USD spending limit before running this block.
The prompts below collect those choices; they do not supply a default authorization or budget.
The verified snapshot supports `gpt-4.1-mini-2025-04-14`. An unset PowerShell variable supplies
no argument, causing `argument --model: expected one argument` before any provider call.
Use an argument array instead of backtick continuations:

```powershell
$authorizedModel = (Read-Host 'Explicitly authorized model').Trim()
$authorizedUsdLimit = (Read-Host 'Explicitly authorized spending limit in USD').Trim()
if ([string]::IsNullOrWhiteSpace($authorizedModel) -or [string]::IsNullOrWhiteSpace($authorizedUsdLimit)) {
  throw 'A model and spending limit must both be explicitly chosen; no run started.'
}
$benchmarkArguments = @(
  'run', 'python', 'scripts/run_hybrid_evaluation.py'
  '--mode', 'hybrid-live', '--allow-live'
  '--manifest', 'work/hybrid-live-synthetic/corpus-20261011/manifest.json'
  '--model', $authorizedModel, '--max-spend-usd', $authorizedUsdLimit
  '--max-documents', '16', '--max-pages', '17', '--max-output-tokens', '4096'
  '--confirm-price-snapshot', 'openai-standard-2026-10-11'
  '--partition', 'all', '--allow-holdout'
  '--output-dir', 'evals/reports/hybrid/live-synthetic-authorized-01'
)
& uv @benchmarkArguments
```

If pasting produces a `PSConsoleReadLine` / `SetCursorPosition` exception, the interactive
line editor is failing before Python runs. In that session, enter the short command
`Remove-Module PSReadLine` separately, then paste the block above, or save it as a private
ignored `.ps1` script and run that script. Do not include terminal prompts such as `PS ...>`
or `>>` in the pasted command. Removing the module affects only that session; it does not
change execution policy or the benchmark's authorization, privacy or spending controls.

`--partition development` needs limits of at least 8 documents/8 pages and no holdout opt-in.
`--partition unseen` needs at least 8 documents/9 pages and `--allow-holdout`. Limits are strict
preflight ceilings on the entire selected partition, not silent truncation. Both corpus and
aggregate directories must be fresh. The runner reserves its output directory before calling
the provider; an interrupted run leaves that directory unavailable for reuse. Reports never
overwrite a historical run. No raw response, quote, source text, image, identifier, note,
credential or local path is printed or exported.

## Aggregate measurements and denominators

JSON and standalone Markdown contain the same allowlisted aggregate tree, corpus fingerprint,
source revision plus working-tree state, exact model/price profile, prompt/extractor/schema and
matching versions, configured limits and limitations. They separate development, reserved and
combined metrics. Fake clients are identified as `fake-provider`, not `hybrid-live`.

- Each mode runs on the same extracted document and has the full selected document denominator.
  Header exact match is successful extracted/correct values per document for each of six fields.
- Exact lines are matched as a multiset of all four fields, with no order-based alignment or
  duplicate credit. Report TP/FP/FN, labelled/predicted row counts, precision, recall and F1.
- Grounded-value acceptance is grounded non-null proposals / non-null proposals, including
  grounded cells later rejected by the row gate. Promoted cells and disagreements are separate.
- Row precision is source-label-correct associations / all accepted associations; unscorable
  associations stay in its denominator and are shown separately. Coverage is accepted / proposed
  candidate rows; abstention is rejected / proposed candidate rows. None is inferred from order.
  Coverage against deterministic rows considered on successful responses is reported too, so a
  missing candidate row cannot make candidate-relative coverage alone appear complete.
- False value promotions use all promoted cells; false financial promotions use promoted numeric
  cells; false cross-row promotions use promoted line cells. Value and role evidence both matter.
  Unscorable promotions are explicit, not credited as correct. Null rates mean zero denominator.
  An unknown row anchor is unscorable, not a confirmed cross-row error; numeric and line-cell
  unscorable counts are shown separately from confirmed false promotions.
  Wrong-value and wrong-financial-role counts are also separate; they can overlap on one cell.
- Review/MATCHED counts are per-mode documents. False automatic matches use independently
  labelled incomplete/ambiguous cases or predictions failing source-role/value/row truth checks
  as their denominator. Unresolved-row review routing has an additional issue-specific count.
- Provider failures use attempted requests; budget/accounting refusals are separate. Failed,
  unrouted and budget-skipped cases retain deterministic output and remain in paired denominators.
- p50/p95 provider wall latency includes failed requests; total per-document latency includes
  source extraction, deterministic parsing and, when routed, rendering/request/fusion. Corpus
  verification, report computation and synthetic safety scoring are excluded from these times.
- Token totals have explicit known/unknown request denominators. Report known-usage estimated
  cost, nullable total cost estimate and the distinct reserved charge upper bound/spending limit.

Financial-column semantics and candidate-only rows remain limitations of 0.5.0. A poor/null gain,
unsafe promotion or excess review workload is a valid result, not grounds to change matching or
claim success. This benchmark creates no live-model findings until an authorized run completes.
