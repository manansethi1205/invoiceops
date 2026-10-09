# Invoice line-item coverage diagnosis and bounded candidate

InvoiceOps keeps perception separate from deterministic arithmetic, matching, review, risk and
payment boundaries. This slice measures invoice line parsing and adds an opt-in two-column table
mode. The production worker and read-path strategy preference remain unchanged.

## Scope and method

The same fixed 500-document validation manifest is used for both OCR modes and both extractors.
Its SHA-256 is recorded in each aggregate report. The entire validation split is observed
development data, not a fresh holdout or a production accuracy claim.

The first report measures `deterministic-baseline@0.2.0` before changing the parser. A separate
precomputed-OCR probe completes earlier while end-to-end OCR runs. The comparison reruns baseline
and `deterministic-line-coverage@0.4.0` on identical text objects per document. Source text can
be reused only from a dedicated container tmpfs; the runner refuses host filesystem caching.

No source documents, OCR, page images, text, IDs, raw predictions, evaluator matchings, credentials
or local filesystem paths are added to the repository. The existing manifest is consumed without
modification. No model provider is called. Frozen reports are never reused as output directories.

## Diagnostic definitions

- Visual construction: pages with words, word tokens, visual rows, and annotated line/page groups
  with no, one, or multiple token rows. Multiple rows can represent legitimate wrapping.
- Header detection: detected headers/pages and rejected anchor signatures. Bounded probes count
  specific known missing-gate patterns; they do not print the observed header text.
- Rejection: body rows lacking descriptions/numeric support, description-only rows, ignored
  rows, footer closures and rows outside active sections.
- Emission: documents emitting lines, actual emitted line count and extracted quantity fields.
- Annotation attribution: each annotated line/page group is assigned to its earliest observed
  bottleneck. Token-center containment is diagnostic, not official DocILE scoring.

The annotation partition uses all LIR fields, including unsupported classes. The legacy counter
`line_groups_numeric_cells_on_multiple_rows` is a non-description alignment proxy: it also
includes codes/dates and is not proof of a financial-cell construction error. The official
supported-field metric denominators remain separate: 1,836 description annotations and 1,576
quantity annotations, or 3,412 fields together. Counts of pages, rows, groups and fields must not
be mixed.

## Measured diagnosis

| Frozen baseline diagnostic | End-to-end | Precomputed OCR |
|---|---:|---:|
| Validation documents | 500 | 500 |
| Pages | 635 | 635 |
| Visual rows | 19,125 | 18,951 |
| Pages with a detected table header | 32 | 36 |
| Annotated line/page groups | 2,543 | 2,543 |
| Groups on a page without a detected header | 2,236 | 2,328 |
| Groups with no contained OCR/text tokens | 105 | 5 |
| Groups with rejected body rows | 142 | 127 |
| Groups reaching a probable item row | 60 | 83 |
| Documents emitting lines | 18 | 22 |
| Emitted lines | 69 | 93 |
| Explicit description + line-total headers lacking quantity/unit-price anchors | 39 | 43 |

Header non-detection dominates, at 87.93%/91.55% of annotated line/page groups. This does not establish
split headers as the cause. Rejected description-plus-unit-price signatures also occur, but
opening those without quantity or a total would require a separate row-admission decision.
The selected pattern already has a printed total and therefore can reuse existing admission
semantics without inferring any money.

## One bounded improvement

The frozen table-header gate requires description, line total and at least one quantity/unit-price
anchor. The candidate adds an explicit **description + line-total table mode**:

- Require two unique known labels in one visual row, no digits/prose, and at least 0.02 normalized
  horizontal separation. No bare-price/total aliases or split-header combinations are added.
- Open the mode only outside an active frozen three/four-column section. Existing frozen sections
  retain their parser behavior.
- Reuse original cell parsing and line conversion. Require one independently numeric monetary
  token, rejecting multiple numbers instead of concatenating them into a fabricated amount.
- Keep absent quantity and unit price `MISSING`, with no evidence. Never calculate them.
- Restrict description-only continuation to a unique nearby item with gap at most 0.03 normalized
  page height. Equidistant, distant and cross-page continuations are not attached.
- End the new mode at printed summary, bank/terms/signature or explicit prose endings. Legitimate
  descriptions such as tax consulting and total replacement kits remain items.

These bounds belong to this one two-column grammar. They are not changes to the frozen parser,
hybrid routing, matching tolerances, canonical supporting records or approval decisions.
New observations can still be wrong; incomplete or contradictory evidence remains reviewable.

## Baseline versus candidate

All rows use the same 500 documents in each OCR mode. Counts use official supported-field
DocILE scoring. Arrows run from frozen 0.2.0 to opt-in 0.4.0.

| Mode / field | GT denominator | Predictions | TP | FP | FN | Precision % | Recall % | F1 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| End-to-end description | 1,836 | 69 -> 71 | 30 -> 31 | 39 -> 40 | 1,806 -> 1,805 | 43.478 -> 43.662 | 1.634 -> 1.688 | 3.150 -> 3.251 |
| End-to-end quantity | 1,576 | 44 -> 44 | 42 -> 42 | 2 -> 2 | 1,534 -> 1,534 | 95.455 -> 95.455 | 2.665 -> 2.665 | 5.185 -> 5.185 |
| End-to-end supported micro | 3,412 | 113 -> 115 | 72 -> 73 | 41 -> 42 | 3,340 -> 3,339 | 63.717 -> 63.478 | 2.110 -> 2.140 | 4.085 -> 4.139 |
| Precomputed description | 1,836 | 93 -> 95 | 46 -> 47 | 47 -> 48 | 1,790 -> 1,789 | 49.462 -> 49.474 | 2.505 -> 2.560 | 4.769 -> 4.868 |
| Precomputed quantity | 1,576 | 50 -> 50 | 46 -> 46 | 4 -> 4 | 1,530 -> 1,530 | 92.000 -> 92.000 | 2.919 -> 2.919 | 5.658 -> 5.658 |
| Precomputed supported micro | 3,412 | 143 -> 145 | 92 -> 93 | 51 -> 52 | 3,320 -> 3,319 | 64.336 -> 64.138 | 2.696 -> 2.726 | 5.176 -> 5.229 |

End-to-end emitted lines increase from 69 to 71, with emitting documents 18 to 20 and header
pages 32 to 36. Precomputed emitted lines increase from 93 to 95, with emitting documents
22 to 24 and header pages 36 to 42. Page denominators are 635; document denominators are 500.
Header-missing annotated groups fall only from 2,236 to 2,232 and from 2,328 to 2,318 out
of 2,543 groups. Visual-row construction and extracted quantities are unchanged.

This is a practical null result: each mode adds one description true positive and one false
positive. Supported micro precision declines while F1 improves by only about 0.05 percentage
points. Positive synthetic tests establish the bounded grammar, not useful generalization.
The candidate is not promoted, and no second parser pattern was tuned on this split.

## Verification and change inventory

- Focused parser, layout, diagnostic, hybrid-router and matching tests: 85 passed.
- Repository tests excluding Docker/private-DocILE markers: 448 passed, 9 deselected.
- Repository Ruff and strict mypy checks passed; mypy covered 120 source files including the runner.
- Docker synthetic extraction holdout: 15/15 schema-valid documents.
- Offline matching, three-way, supporting and hybrid-replay evaluations passed with zero false
  automatic matches or false canonical creations in their applicable scenarios.
- Both DocILE modes completed for baseline and candidate; no live model calls were made.

Source changes: invoiceops/evaluation/line_coverage.py,
invoiceops/extraction/line_coverage_candidate.py, invoiceops/extraction/version.py,
scripts/analyze_docile_line_coverage.py, tests/evaluation/test_line_coverage.py,
and tests/unit/test_line_coverage_candidate.py.
Documentation changes: this file, docs/evaluation.md, docs/roadmap.md, and README.md.
The six new report artifacts are the JSON/Markdown pairs listed below. Frozen parser, production
selection, input manifest, historical reports, canonical PO/receipt creation, matching,
review, risk and payment code are unchanged.

## Report artifacts

Each listed directory contains aggregate-only `report.json` and `report.md`:

- `evals/reports/docile/line-coverage-baseline-0.2.0-500`
- `evals/reports/docile/line-coverage-precomputed-probe-500`
- `evals/reports/docile/line-coverage-0.4.0-comparison-500`

JSON includes per-field official TP/FP/FN, precision/recall/F1/AP, full official LIR metrics,
supported micro metrics and stage counters. Markdown includes all counts and denominators.
Official location-based LIR F1 is not exact-text accuracy. Gross/net line money fields remain
unmapped because InvoiceOps does not encode their tax basis.

## Reproduction

Set `DOCILE_DATASET_PATH` to the extracted dataset directory containing `val.json`, not the
DocILE source checkout. Build the evaluation image from current source and use fresh outputs:

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  -m scripts.analyze_docile_line_coverage `
  --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/validation-500.json `
  --output-dir evals/reports/docile/line-coverage-baseline-new-run `
  --baseline-only

docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  -m scripts.analyze_docile_line_coverage `
  --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/validation-500.json `
  --output-dir evals/reports/docile/line-coverage-comparison-new-run
```

Omitting `--mode` evaluates both modes; `--mode precomputed_ocr` needs no Tesseract. Optional
`--use-private-cache` is accepted only inside a container with a dedicated `/private-cache`
tmpfs. This task's temporary container and private cache are removed after evaluation.

## Limitations and rollout

This bounded grammar does not handle split headers, unknown aliases, bare-price tables,
unlabelled columns, rotated pages or cross-page descriptions. It conservatively rejects numeric
values split across multiple tokens. Close prose within a description column can still be
semantically ambiguous; no general prose-understanding claim is made.

Keep the strategy opt-in. Before production adoption, use independent de-identified invoice
layouts, assess precision and exception workload, add persisted-version/strategy-selection tests,
and verify routing against realistic incomplete/mismatched invoices. Do not change canonical
confirmation, review ownership, matching/risk rules or payment authority during that rollout.
