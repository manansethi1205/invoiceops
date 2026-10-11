# Private human-labelled deterministic baseline

This harness evaluates actual PDF, PNG and JPEG bytes using `EvaluationRunner._evaluate`,
`DocumentTextExtractor` and the frozen `deterministic@0.2.0` extractor. It reuses
`ManifestAdapter`, `GroundTruthInvoice`, canonical normalization and order-preserving row
alignment. It does not initialize a model/provider, use oracle candidates, perform supplier/PO
discovery, or run matching, review, approval or payment. The authorized private corpus has now
been evaluated; see the measured baselines in [the evaluation guide](evaluation.md#private-human-labelled-real-invoice-baseline).
Ordinary tests continue to use synthetic documents only.

Legacy manifests, truth, metrics and report writers retain their behavior. The existing writer
exports case-level values and must **not** be used for a publishable private-corpus result.
DocILE's official location-based KILE/LIR scoring is a different task and remains separate.

## Private inputs and annotation contract

Use only invoices you are authorized to evaluate. Start with 20–30 invoices covering unfamiliar
layouts, embedded-text and scanned inputs, multi-page tables, repeated amounts and incomplete
financial columns. This is a selected diagnostic sample, not population prevalence or a fresh
holdout. Human reviewers must inspect the original files independently of predictions before
freezing their labels. The harness cannot establish permission, genuine invoice status, or
independent authorship from a JSON attestation.

Put the corpus below ignored, untracked `work/real-invoice-private/`, for example:

```text
work/real-invoice-private/corpus-01/
  manifest.jsonl
  documents/invoice-001.pdf
  annotations/invoice-001.json
```

The JSONL manifest uses the existing manifest schema; this example is synthetic:

```json
{"document_id":"local-001","split":"development","document_path":"documents/invoice-001.pdf","content_type":"application/pdf","ground_truth_path":"annotations/invoice-001.json"}
```

Each ID must be unique. A manifest has one split. `holdout` requires `--allow-holdout`; inspecting
results makes that sample observed development data. Content types are `application/pdf`,
`image/png` and `image/jpeg`. Paths must be relative descendants of the manifest directory:
absolute/drive paths, `..`, missing files and symlinks/junctions are refused. Git must confirm
that the manifest, source files and annotations are ignored and untracked. Place annotations
next to the manifest hierarchy, rather than using the legacy adapter's permissive `../` paths.

Annotations require `annotation_version: human-invoice-v1` and `provenance: human`. This is a
distinct evaluation-only schema, not a production `Invoice` or a legacy ground-truth file.
Every field has one of three statuses:

- `present`: a directly observable value and at least one evidence box are required.
- `absent`: the reviewer checked the whole invoice and confirmed no printed value for this role.
- `not_annotated`: unknown, unresolved, illegible, competing roles or not reviewed; excluded.

Absent/unannotated fields cannot carry values or boxes. Omitted fields default to
`not_annotated`, never absent. Dates use ISO dates, financial values decimal strings, currencies
an explicitly justified ISO code, and descriptions the printed description. Evidence boxes
use zero-based pages and normalized displayed-page coordinates, with positive area. Do not use
OCR token coordinates without checking rotation and page dimensions. All box pages must exist
when the source is decodable; unverifiable pages in malformed inputs cannot establish accuracy.

For illustration, a deliberately partial **synthetic** annotation is:

```json
{
  "annotation_version": "human-invoice-v1",
  "provenance": "human",
  "invoice_number": {
    "status": "present", "value": "SYN-001",
    "evidence": [{"page": 0, "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.3, "y1": 0.14}}]
  },
  "tax": {"status": "absent"},
  "total": {"status": "not_annotated"},
  "line_items": {"status": "not_annotated", "rows": []}
}
```

Label all six headers: invoice number, date, currency, subtotal, tax and total. Never derive a
missing monetary value using arithmetic or adopt the extractor's output as ground truth.
Distinguish subtotal, tax, gross invoice total, summary totals and printed net line totals.
If a currency symbol or amount role is ambiguous, mark it unannotated rather than guessing.

For a table, `line_items.status` is `present` and `rows` is a nonempty, complete list in visual
order. Each row contains description, quantity, unit_price and line_total field objects with
the same three statuses and evidence format. Use multiple boxes for wrapped descriptions or
multi-page evidence. Missing printed cells are explicitly absent; unclear cells are unannotated.
Do not label summary totals as item rows or infer a quantity/price/line total. A checked invoice
with no genuine item table uses `absent` and empty rows. An incomplete row inventory must use
`not_annotated` and empty rows. Any unannotated cell in a present table excludes that entire
document from exact-row scoring, with a separate partial-table count.

## Aggregate metrics and privacy

Fresh reports explicitly stamp `real-input-human-v1`. Loading a report without `metric_version`
returns `None`; it never silently claims the current scorer. JSON contains allowlisted metric
definitions and counters, with numerator, denominator and rate for each fraction. Markdown
includes the same aggregate tree and definitions.

All attempted documents, including malformed files, OCR failures and schema failures, remain
in annotated header and complete-table row denominators. OCR readiness uses the existing
English/Tesseract checks at the actual fallback stage. An unavailable engine records an OCR
failure; there is no synthetic token substitution, silent omission or fallback model. Encrypted
and unreadable documents fail safely. MuPDF's deferred image-decode exception is translated
only in this evaluation wrapper to the existing unreadable-document reason.

- Header coverage: extracted on present labels / present labels.
- Header present exact: canonical value matches / present labels; conditional exact uses only
  extracted-on-present as its denominator. Normalization is the existing evaluator's, including
  identifier normalization and decimal equality, not literal character equality.
- Absence: schema-valid abstentions / explicitly absent labels. False extracted values on
  absent labels and failed absent opportunities are counted separately. Ambiguous output is
  an abstention. Combined annotated accuracy is (present exact + correct absence) / (present
  + absent). Unannotated fields never enter these denominators.
- Evidence-supported exact: value exact plus each human box center inside a same-page predicted
  span whose text equals its contained source tokens; denominator is present labels. Reported
  separately from value accuracy. This tests a bounded location/text condition, not semantic
  role adjudication, unique-token binding, or official DocILE scoring.
- Exact rows: existing order-preserving DP alignment; all four canonical cells must match,
  including explicit absence. TP is the number of exact aligned rows, FP=predicted−TP,
  FN=labelled−TP. Precision=TP/(TP+FP), recall=TP/(TP+FN), F1=2TP/(2TP+FP+FN).
  Only fully labelled tables and explicit table absence contribute. Supported exact-row counts
  additionally test evidence for every present cell. Empty denominators are null.
- Operational: attempted/failed documents, closed failure categories, schema valid / attempted,
  known/unknown page documents and total known pages. Known page counts survive OCR failures;
  malformed image containers are not credited as readable pages. OCR attempted/completed/failed
  documents and completed OCR pages are separate; a later failure can leave partial completed
  pages. p50/p95 use nearest-rank latency over **all** attempts, including metadata probing,
  extraction and schema validation, excluding manifest I/O, annotation validation and report scoring.
- Mutually exclusive slices: any OCR attempted (`scan_or_ocr`, including mixed PDFs and OCR
  failures), completed extraction without OCR (`embedded_only`), or undecodable/other failures
  before OCR (`unknown`). These are observed input-processing stages, not manually verified
  document types. PDF/PNG/JPEG counts appear within each slice and reconcile to all attempts.

The fingerprint hashes source bytes paired with canonical human annotations, sorts the pair
hashes and preserves multiplicity. Renaming IDs or files and reordering manifest records do not
change it; changed source bytes, values, statuses or boxes do. Revision/worktree state identify
the source used; do not relabel frozen reports as runs from a later commit. The OCR version is
the CLI readiness version; the integrated Tesseract library version is not exposed by PyMuPDF.
The backend's PyMuPDF version and native thresholds are recorded separately.

Public JSON/Markdown contain no IDs, filenames, tags, labels, field values, OCR, images,
quotes, raw predictions, private paths or exception messages. Native/Python extraction output
is discarded for this single-process CLI. It is not safe to embed its process-wide stdout
suppression in a concurrent server. Public output must be a new leaf below
`evals/reports/real-input/`; existing directories and linked paths are refused.

Case-level results and human labels are written only when `--private-diagnostics` explicitly
names a fresh ignored/untracked descendant of `work/real-invoice-private/`. Do not publish or
stage that directory. It includes sensitive predictions/evidence and annotations. Filesystem
ignore guards are not encryption or access control; use appropriate host permissions privately.

## Run template: requires an authorized human-labelled corpus

These are templates for a new authorized corpus and fresh output directory. The measured runs
are documented separately in the evaluation guide; do not overwrite their directories.
With dependencies already installed, prevent uv from accessing the network:

```powershell
$env:UV_OFFLINE = '1'
uv run python scripts/run_private_invoice_evaluation.py `
  --manifest work/real-invoice-private/corpus-01/manifest.jsonl `
  --output-dir evals/reports/real-input/private-baseline-01
```

Optional private case-level output:

```powershell
uv run python scripts/run_private_invoice_evaluation.py `
  --manifest work/real-invoice-private/corpus-01/manifest.jsonl `
  --output-dir evals/reports/real-input/private-baseline-02 `
  --private-diagnostics work/real-invoice-private/diagnostics/baseline-02
```

Configure an installed Tesseract English runtime privately using process-local PATH and
TESSDATA_PREFIX if necessary. No runtime installation, downloads, model access or network calls
are performed by this CLI. For a fully offline invocation independent of uv dependency setup,
use `.\.venv\Scripts\python.exe` in place of `uv run python`.

Inspect aggregates and private error cases before making parser decisions. Inconsistent manual
roles, incorrect boxes, annotation coverage and selective layouts can bias this baseline.
Value exact alone does not prove trustworthy financial semantics or safe automatic payment.
