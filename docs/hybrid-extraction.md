# Evidence-grounded VLM fallback

`hybrid-routed@0.3.0` is a perception fallback, not an autonomous AP agent. It always persists
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
token match, and permits fuzzy fallback only at or above 92. The accepted bounding box is the union
of matched source tokens and retains embedded-text/OCR provenance.

Fusion is conservative: agreement retains deterministic evidence; a grounded value may fill a
missing/ambiguous slot; a grounded conflict makes the canonical field ambiguous; an ungrounded
candidate is rejected. The same rule applies cell-by-cell to line items. Confidence remains
uncalibrated diagnostic metadata.

## Reliability and privacy

`ModelCall` stores routing, fingerprint, provider/model/prompt version, token usage, latency,
sanitized candidates, grounding/fusion outcomes, and safe error codes. It never stores API keys,
authorization headers, base64 images, raw HTTP requests, or hidden reasoning. Successful attempts
are reused by fingerprint. Exactly-once external execution is not claimed because a crash between
the response and database commit can lead to an at-least-once retry.

The feature is disabled by default, with no default model. Provider/render/schema failure completes
0.3.0 with the usable deterministic invoice. Matching prefers a successful 0.3.0 run but immutable
historical matches continue referencing the extraction run used when they were created.
