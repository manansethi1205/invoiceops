# Evidence-grounded VLM fallback

`hybrid-routed@0.5.0` is a perception fallback, not an autonomous AP agent. It always persists
`deterministic-baseline@0.2.0` first. It adds deterministic review routing for unresolved row association, without changing
arithmetic tolerances, approval, or payment authority.

## Routing policy

The pure router invokes the provider for these ordered, deduplicated reasons:

- missing or ambiguous invoice number, invoice date, currency, or total;
- no line items or a line missing description, quantity, unit price, or line total;
- `subtotal + tax` or `quantity × unit price` differs by more than `0.02`;
- OCR supplies at least 50% of pages (the boundary is inclusive).

Completeness is reported across six header fields and four cells per line. Critical completeness
uses the four critical fields. Model confidence does not participate in initial routing.

## Trust and evidence boundary

The provider receives bounded in-memory PNG page renders and returns strict, extra-forbid candidate
JSON. Dates and decimals remain strings until application normalization. Document contents are
explicitly treated as untrusted data; the request exposes no tools. The service ignores any model
box, normalizes the evidence quote, searches only the stated page, requires a unique contiguous
token match, and permits fuzzy quote-location fallback only at or above 92. A located quote does
not establish its proposed value. Inside that quote, the service requires exactly one contiguous
whole-source-token subspan whose field-specific normalization equals `raw_value`. Value binding
itself is never fuzzy. Accepted evidence contains only that value subspan's source tokens and
bounding box, with their embedded-text/OCR provenance; label tokens are excluded.

For example, value `999` with a uniquely located quote `100` is rejected. `Total 100.00` can
ground value `100` when its value subspan is unique. Two different amounts in a quote do not
compete if only one normalizes to the proposed value; repeated equivalent values do compete.
Even overlapping normalized spans compete: separate `USD` and `100` tokens yield both `USD 100`
and `100`, so that case conservatively abstains. Currency attached to one monetary token, such
as `$100.00`, remains usable. Dates, currency names and monetary formatting use existing field
normalizers; this change adds no aliases or inferred amounts. Numeric/date fuzzy quote lookup
also requires unchanged digit runs, so it cannot substitute a digit even when the proposed value
matches the altered source. Fuzzy label location may work when the value is separately exact.

Safe rejection reasons are `VALUE_NOT_FOUND_IN_QUOTE`, `VALUE_NOT_UNIQUE_IN_QUOTE` and
`QUOTE_DIGITS_MISMATCH`. Existing duplicate-quote, missing-quote, wrong-page and invalid-value
reasons remain intact. These codes carry no source text. Rejection leaves the deterministic
field unchanged, including existing ambiguity; grounded deterministic conflicts still abstain.
Candidate-only rows abstain without creating invoice lines; their uncertainty remains explicit.

Fusion is conservative: agreement retains deterministic evidence; a grounded value may fill a
missing/ambiguous slot; a grounded conflict makes the canonical field ambiguous; an ungrounded
candidate is rejected. This rule applies to line cells only after a unique row association. Confidence remains
uncalibrated diagnostic metadata.

## Source-based row association (0.5.0)

All claimed candidate cells are grounded first. A grounded description supplies the page and
source-token anchor; embedded/OCR provenance must agree with the actual source. The complete row
must occupy one page and a vertical envelope at most 0.06 of normalized page height. Each cell
must vertically overlap description evidence. This supports bounded wrapped descriptions when
source reading order permits contiguous grounding. Cross-page individual rows abstain; separate
rows on separate pages can associate normally.

Association requires shared description source tokens with exactly one deterministic row, no
other description row touched by any cell, and a unique one-to-one mapping. Array position,
monetary equality, arithmetic and model confidence never establish identity. Repeated values
may work with unique contextual quotes and distinct evidence. Duplicate/reused source evidence,
missing/ungrounded anchors, incoherent cells, ambiguous anchors and candidate-only rows abstain.
No candidate-only row is added. Deterministic line order, values and evidence remain unchanged on
row rejection; associated missing cells may be filled, while grounded conflicts remain ambiguous.

Safe row diagnostics are `anchor_missing`, `cell_ungrounded`, `incoherent_geometry`,
`cross_row_cells`, `reused_evidence`, `ambiguous_anchor`, `candidate_only` and `associated`.
They record no source text. The persisted summary includes the explicit association mapping.
Any abstained candidate row or deterministic row not represented by an association adds
`hybrid_row_association_unresolved` to the Invoice's additive `extraction_issues` field.
An empty candidate row list therefore cannot silently conceal row disagreement.

Hybrid outputs use `invoice-v2`; older invoices without issues load with an empty list. Empty issues are omitted when serializing,
so deterministic invoice-v1 output shape is preserved. Matching
contracts are `matching-v3` and `three-way-v3`. An extraction issue yields the failed deterministic
check `EXTRACTION_ROW_ASSOCIATION_UNRESOLVED`, forcing NEEDS_REVIEW and preventing three-way
allocations. Existing review workflows handle that decision. Historical extraction runs, matching
results and policy snapshots remain immutable; neither supporting records nor payment authority
changes.

Limitations: the 0.06 envelope is a conservative bound, not a calibrated population threshold.
Rotated layouts, unusually tall wraps, multi-page individual rows, lost anchors and candidate-only
rows sacrifice coverage. Geometry does not establish financial column semantics. Fuzzy quote
ambiguity and the existing exact value-binding requirements still apply. No live pilot is justified
by these synthetic results alone.

## Reliability and privacy

`ModelCall` stores routing, fingerprint, provider/model/prompt version, token usage, latency,
sanitized candidates, grounding/fusion outcomes, and safe error codes. It never stores API keys,
authorization headers, base64 images, raw HTTP requests, or hidden reasoning. Successful attempts
are reused by fingerprint. Exactly-once external execution is not claimed because a crash between
the response and database commit can lead to an at-least-once retry.

The feature is disabled by default, with no default model. Provider/render/schema failure completes
0.5.0 with the usable deterministic invoice. Current extraction read paths prefer a successful
0.5.0 run, then the 0.2.0 deterministic baseline. Earlier 0.3.0 and 0.4.0 hybrid runs are retained but
excluded from current selection; immutable historical matches keep referencing their original
run. The version changes the request fingerprint, so an old-version model call is not reused
as a new-version result. Within 0.5.0, retries reuse persisted candidates and apply the new binding
checks; completed runs and provider failures remain idempotent. The invoice schema and prompt
are `invoice-v2` and the unchanged `invoice-vision-v1`. Supporting-document extraction is unchanged.
Its former shared quote locator is frozen separately in `supporting_quote_grounding.py`; the
supporting hybrid continues applying its existing value/role checks and retains its own version
and quote provenance. This prevents an invoice-only patch changing supporting behavior silently.

## Offline safety verification

The 0.4.0 replay uses the same 12 synthetic stress documents as the frozen 0.3.0 report, without
a live provider. Header coverage is 67/72 fields (93.06%), critical coverage 43/48 (89.58%), and
exact line-item F1 is 1.0. These measurements are unchanged; the fix is a trust-boundary repair,
not a measured accuracy improvement. Adversarial unit tests separately cover unrelated values,
multiple/repeated amounts, exact normalized dates/currencies, fuzzy OCR labels, digit substitutions,
line-item rejection, evidence boxes and persisted-run selection/retries. Replay latency and usage
are simulated, and no live-model accuracy or cost is claimed.

The frozen [0.4.0 report](../evals/reports/hybrid/0.4.0-replay/report.md) retains the original
0.3.0 report unchanged. The replay writer refuses existing output directories.

Verification includes adversarial invoice grounding, supporting quote-provenance preservation,
service/routing/provider/schema/ingestion/matching and replay tests. No live-model or Docker stack
test was run. The frozen 0.4.0 report records its parent revision because it was generated before commit
`6daf2bc`. That fix is now committed; the report has not been relabeled or overwritten.

Final results: 119 focused tests passed; repository checks passed with 527 passed, two Windows
symlink-permission skips and nine Docker/private-data tests deselected. Ruff and strict mypy
passed (123 files including the CLI). Privacy checks passed for all 21 changed files, all 52
historical report files match HEAD, and the frozen supporting locator's AST matches its prior
implementation. UTF-8/mojibake checks passed on 44 Markdown files; git diff --check passed.


## Row association safety evaluation

The [0.5.0 replay](../evals/reports/hybrid/0.5.0-replay/report.md) reuses the 12 historical
synthetic documents and preserves their header measurements. Its row candidates are empty, so
it is not evidence of row-association coverage. The separate
[row stress report](../evals/reports/hybrid/0.5.0-row-alignment/report.md) uses 15 deterministic
synthetic scenarios, including reordered, inserted/deleted, repeated-description/amount,
wrapped, multipage, OCR, missing-anchor and reused/cross-row evidence cases. Associations are
checked against explicit expected mappings; partial-row trials remove quantity cells to measure
actual promotions. False automatic matches are counted against independently specified review
expectations, not merely the issue flag produced by fusion. Reports refuse existing directories.
Both reports identify the parent revision `6daf2bc` from which their source working tree was
derived. They were generated before the 0.5.0 changes were committed; the row stress report
explicitly records that generation-time uncommitted source state. Those references describe the
original runs and must not be relabeled as runs from a later implementation commit.
No live models or private documents were used. These are observed synthetic development cases,
not an independent holdout or DocILE accuracy measurement.


In the 15-case synthetic safety regression, association precision is 20/20 (100%), candidate-row coverage 20/29
(68.97%) and abstention 9/29 (31.03%). Partial-row trials correctly promote 20/30 removed quantity
cells, with 0/20 cross-row promotions. Complete-invoice trials require review in 9/15 cases:
8/15 carry the new row issue; one further duplicate-description case is blocked by existing
matching ambiguity checks. There are 0/9 false automatic matches among independently specified
review cases. These are checks against fixed synthetic expected mappings, not evidence of
live-model row-association precision or population-level performance.

Verification for 0.5.0: 202 focused tests; repository suite 571 passed, two Windows symlink skips
and nine Docker/private-data tests deselected. Ruff and strict mypy pass (125 source files).
Both new offline reports reproduce. All 54 historical reports match HEAD; privacy checks cover
29 changed files against all 500 private manifest IDs and host paths, and UTF-8/mojibake checks
cover 46 Markdown files. `git diff --check` passes. Supporting records, value grounding,
matching arithmetic/allocations, review/risk/payment authority and worker defaults are unchanged.
