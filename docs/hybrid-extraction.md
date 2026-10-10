# Evidence-grounded VLM fallback

`hybrid-routed@0.4.0` is a perception fallback, not an autonomous AP agent. It always persists
`deterministic-baseline@0.2.0` first and never changes arithmetic, matching, approval, or payment
policy.

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
Candidate-only rows with no accepted cells are omitted rather than adding empty invoice rows.

Fusion is conservative: agreement retains deterministic evidence; a grounded value may fill a
missing/ambiguous slot; a grounded conflict makes the canonical field ambiguous; an ungrounded
candidate is rejected. The same rule applies cell-by-cell to line items. Confidence remains
uncalibrated diagnostic metadata. **Remaining limitation:** line-item fusion aligns deterministic
and candidate rows by list index, not by source geometry or stable row identity. Value grounding
does not establish financial column semantics or prevent cells from different rows being aligned.
This separate row-alignment risk remains to be addressed before a live-model pilot.

## Reliability and privacy

`ModelCall` stores routing, fingerprint, provider/model/prompt version, token usage, latency,
sanitized candidates, grounding/fusion outcomes, and safe error codes. It never stores API keys,
authorization headers, base64 images, raw HTTP requests, or hidden reasoning. Successful attempts
are reused by fingerprint. Exactly-once external execution is not claimed because a crash between
the response and database commit can lead to an at-least-once retry.

The feature is disabled by default, with no default model. Provider/render/schema failure completes
0.4.0 with the usable deterministic invoice. Current extraction read paths prefer a successful
0.4.0 run, then the 0.2.0 deterministic baseline. Quote-only 0.3.0 hybrid runs are retained but
excluded from current selection; immutable historical matches keep referencing their original
run. The version changes the request fingerprint, so an old-version model call is not reused
as a new-version result. Within 0.4.0, retries reuse persisted candidates and apply the new binding
checks; completed runs and provider failures remain idempotent. The invoice schema and prompt
remain `invoice-v1` and `invoice-vision-v1`. Supporting-document extraction is unchanged.
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

The fresh [0.4.0 report](../evals/reports/hybrid/0.4.0-replay/report.md) retains the original
0.3.0 report unchanged. The replay writer refuses existing output directories.

Verification includes adversarial invoice grounding, supporting quote-provenance preservation,
service/routing/provider/schema/ingestion/matching and replay tests. No live-model or Docker stack
test was run. The report records the parent Git revision while this fix remains uncommitted.

Final results: 119 focused tests passed; repository checks passed with 527 passed, two Windows
symlink-permission skips and nine Docker/private-data tests deselected. Ruff and strict mypy
passed (123 files including the CLI). Privacy checks passed for all 21 changed files, all 52
historical report files match HEAD, and the frozen supporting locator's AST matches its prior
implementation. UTF-8/mojibake checks passed on 44 Markdown files; git diff --check passed.
