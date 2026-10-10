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
- Annotation attribution: each annotated line/page group is assigned to an observed
  stage, not a diagnosed cause. Token-center containment is diagnostic, not official DocILE scoring.

The annotation partition uses all LIR fields, including unsupported classes. The legacy counter
`line_groups_numeric_cells_on_multiple_rows` is a non-description alignment proxy: it also
includes codes/dates and is not proof of a financial-cell construction error. The official
supported-field metric denominators remain separate: 1,836 description annotations and 1,576
quantity annotations, or 3,412 fields together. Counts of pages, rows, groups and fields must not
be mixed.

## Measured observations

| Frozen baseline diagnostic | End-to-end | Precomputed OCR |
|---|---:|---:|
| Validation documents | 500 | 500 |
| Pages | 635 | 635 |
| Visual rows | 19,125 | 18,951 |
| Pages with a detected table header | 32 | 36 |
| Annotated line/page groups | 2,543 | 2,543 |
| Groups with contained tokens and no detected page header | 2,236 | 2,328 |
| Groups with no contained OCR/text tokens | 105 | 5 |
| Groups with rejected body rows | 142 | 127 |
| Groups reaching a probable item row | 60 | 83 |
| Documents emitting lines | 18 | 22 |
| Emitted lines | 69 | 93 |
| Explicit description + line-total headers lacking quantity/unit-price anchors | 39 | 43 |

The no-detected-page-header stage accounts for 87.93%/91.55% of annotated line/page groups.
This is an observation, not a root cause: continuation pages may legitimately omit repeated
headers, and document type, token availability or coordinate attribution can change its meaning.
It establishes neither split headers as the cause nor that a header was printed on every page. Rejected description-plus-unit-price signatures also occur, but
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

## Evaluation-only paired header-miss audit

The audit adds no parser rules or extractor version and does not promote the 0.4.0 candidate.
No worker/read-path selection, matching, review, risk, canonical record or payment behavior changes.

The private inventory contains one observation per document/page/line-item ID and OCR mode.
Each group is paired across end-to-end and precomputed OCR. Page-local groups remain distinct
when a line-item ID occurs on more than one page; fields without an ID are counted separately
and excluded from grouping. Coordinates are normalized, pages are zero-based, and the
precomputed adapter keeps normalized boxes even when image dimensions are in pixels.
Containment includes a token center on a boundary; positive box intersection without a
contained center is recorded separately. None of these checks is official DocILE PCC scoring.

Sampling uses seed 1205 and SHA-256 ranks within round-robin joint strata:
invoice/other/unknown type, first/later page, and each mode's header detection, group token
presence and existing rejected-header signature bucket. DocILE tax_invoice is the invoice
stratum; other types include orders and receipts. Forty pairs lacking a detected header in
at least one mode and eight pairs detected in both modes are requested. Controls reserve
capacity first; a combined cap of two selected groups per document applies. Any shortfall,
available/selected strata, achieved document/group counts and mode denominators are explicit.
Signature buckets contain only predefined anchor combinations, never observed header text.

An earlier detected header, earlier LIR page, shared cross-page ID, absent contained tokens,
invalid annotation box, or box overlap without a token center is an observable signal.
It cannot automatically assign continuation, OCR loss, geometry or coordinate error.

The generated private RUBRIC.md requires source-page and token inspection for every assigned
primary explanation. Additional required evidence distinguishes:
tokens_absent, wording_not_supported, geometry_or_row_grouping, continuation_page,
document_not_invoice, annotation_or_coordinate_mismatch and other_or_uncertain.
Detected controls require visual verification of the actual detected row.
Continuation specifically requires inspection of a prior page and verification that the table
continues without a repeated header. Annotation/coordinate explanations require both grouping
and coordinate inspection. Empty labels remain unreviewed; unresolved competing explanations
remain other_or_uncertain. Reviewer notes and inspection checklists never enter public reports.

Private output is accepted only in ignored, untracked work/docile-header-audit-private
subdirectories or the existing dedicated /private-cache tmpfs. Symlinks/junctions, tracked
destinations and existing new-run directories are refused. Raw tokens can stay in tmpfs;
selected images, tokens, annotations, IDs and labels stay private. Routine CLI errors suppress
dataset exception details. Aggregate output must be a fresh evals/reports/docile subdirectory.
Its string/key allowlist rejects case-level keys or accidental private prose.

Preparation and export are separate commands. In the existing evaluation container, provide
a dedicated tmpfs and a fresh private directory:
~~~text
python -m scripts.audit_docile_header_misses prepare
  --dataset-path /data/docile
  --sample-manifest data/docile/manifests/validation-500.json
  --private-dir /private-cache/new-audit
  --cache-dir /private-cache/new-text-cache
~~~
After private visual inspection, edit only the private reviews.json with primary explanations
and required affirmative evidence. Export to a fresh report directory:
~~~text
python -m scripts.audit_docile_header_misses export
  --private-dir work/docile-header-audit-private/new-review
  --output-dir evals/reports/docile/header-miss-audit-new-run
~~~
The first example's private tmpfs artifacts must be copied to a guard-checked ignored directory
before export on the host, or reviewed/exported inside the same running container. Private
tmpfs contents disappear with the container; do not copy the full OCR cache into Git.

Every exported category count uses its selected-mode group denominator. Inspected, unreviewed
and uncertainty counts are separate, and categories reconcile to inspected observations.
Paired disagreements use the selected-pair denominator; reviewer disagreement uses only pairs
inspected in both modes. This equal-stratum qualitative sample is not a representative estimate
for all 2,543 groups. All 500 validation documents are observed development data, not a fresh
holdout; one reviewer provides no independent adjudication.

### Reviewed aggregate result

The fresh [qualitative audit report](../evals/reports/docile/header-miss-audit-500-qualitative/report.json)
scanned all 500 documents. There are 2,543 paired page/line groups in 458 documents with
LIR annotations: 2,365 pairs miss a page header in at least one mode and 178 detect it in both.
No annotated fields lack a line-item ID. Seed 1205 selected 40 miss pairs and eight controls
from 45 documents, with 48 joint strata represented out of 57 and a maximum of two per document.
The sample contains 32 invoice-type and 16 other-type groups; 37 are first-page and 11 later-page.

All 48 groups were inspected in both modes (96 mode reviews; zero unreviewed).
The following primary labels use a denominator of **48 inspected groups per mode**.
Detected labels include eight paired controls plus four groups detected in only that mode.

| Primary review explanation | End-to-end | Precomputed OCR |
| --- | ---: | ---: |
| Tokens absent or damaged | 7 | 4 |
| Unsupported wording | 2 | 5 |
| Geometry or row grouping/rotation | 3 | 0 |
| Continuation without repeated header | 0 | 0 |
| Non-invoice document | 12 | 12 |
| Annotation/coordinate mismatch | 0 | 0 |
| Other or uncertain | 12 | 15 |
| Detected header visually verified | 12 | 12 |
| Total inspected | 48 | 48 |

Of the **36 actual page-header misses per mode**, 12/36 end-to-end and 15/36 precomputed
remain uncertain. Many unresolved tables have missing or competing financial field roles;
an alias or geometry change alone is not justified by those observations. Document type is
an annotation-derived sampling stratum; visual review can disagree with it, and a receipt
or order is not automatically a parser defect. Verified detected rows do not establish
correct column semantics, emitted lines or official LIR accuracy.

Header detection disagrees on 8/48 pairs (four in each direction). Token-center presence
disagrees on 9/48, signature on 17/48, and primary review explanation on 14/48 jointly inspected
pairs. Five groups per mode have token overlap without center containment, zero have invalid
normalized boxes, two share an ID across pages, and ten have prior-page LIR annotations.
These are signals, not confirmed coordinate errors or continuation causes. No continuation
or coordinate mismatch was confirmed in this selected sample; that does not establish absence
from the development split. Synthetic tests cover genuine no-repeat continuation and normalized
coordinate/page/grouping edge cases.

The bounded invoice-only financial-role adjudication below completes this diagnostic gate.
The 12/36 and 15/36 uncertain misses, 12 non-invoice explanations per mode, and mixed categories do
not support one dominant parser fix. Keep financial-role ambiguity intact. This is a qualitative,
stratified, single-reviewer sample of observed development data, not a prevalence estimate,
causal experiment, independent holdout or extraction-quality improvement claim.


Verification: focused audit/coverage/table/parser tests passed (51 passed, one Windows
symlink-permission skip). The synthetic evaluation suite passed (74 passed, one skip,
three real-data tests deselected). Repository Ruff and strict mypy, including the audit runner,
passed (121 source files); git diff --check and UTF-8/mojibake checks passed. An additional
host real-data run initially failed both smoke modes because the configured dataset directory
lacked its validation index. With the dataset root corrected for that check, precomputed OCR
passed and end-to-end failed with a Tesseract/TESSDATA_PREFIX RuntimeError. The audit's actual
500-document OCR preparation ran in the guarded evaluator container; this host smoke limitation
was not bypassed or used to alter frozen behavior. This host Tesseract limitation is not a commit
blocker because actual audit OCR preparation ran in the guarded container. The full official
evaluator was not rerun.

### Invoice-focused financial-role adjudication

The separate [financial-role report](../evals/reports/docile/financial-role-adjudication-500-qualitative/report.md)
and [aggregate JSON](../evals/reports/docile/financial-role-adjudication-500-qualitative/report.json)
freeze a second, evaluation-only selection. The first 48-pair audit, frozen 100/500-document
reports, extractor versions and production selection remain unchanged. All 500 validation
documents are observed development data; this is a nonrepresentative qualitative sample.

Seed 2110 uses deterministic round-robin joint strata for OCR detection direction, page position,
token presence and existing signatures within DocILE's invoice document-type stratum. The
combined cap is two groups per document. All four requested tiers were achieved: 15 previously
unresolved invoice-stratum pairs, 12 fresh both-mode misses, six fresh OCR disagreements and
four fresh both-mode detected controls: **37 pairs from 33 documents**. Fresh tiers exclude
all 45 first-audit documents, which contain 289 invoice-stratum groups. Eligible pools were
15, 1,134, 12 and 81 respectively; two disagreement candidates were encountered and excluded
by the cap. There were no selection shortfalls. The inventory has 1,516 invoice-stratum groups
and 1,027 other-stratum groups, which were excluded. These are group counts, not document counts.

DocILE's invoice stratum is not visual confirmation: **34/37** selected pairs were visually
invoices, **1/37** was not and **2/37** remained unknown in both modes. The source layouts were
29 item tables, six summaries and two lists, each out of 37. A genuine description/charge table
does not establish supplied quantity, unit price or safe payable amounts. Empty financial columns
remain absent/unknown; printed rate alone is not an automatically established unit price. The
rubric records source-visible roles and printed net/tax/gross or summary context separately
from token defects and primary/competing explanations. Arithmetic and annotation-only inference
are prohibited. Amount context is multilabel and never supplies monetary values. Printed-role
judgments concern the selected page/table context, not field accuracy on a particular annotated
row. Sampled groups on the same page repeat context and are correlated observations.

One assistant performed two differently ordered, anonymous source/token review passes. The
second pass could not see first-pass labels through its review artifacts. Pass one was sealed
before pass two was created; both were sealed before explicit adjudication. Blinding removes
labels, tiers, annotations and stage counters, but cannot erase source familiarity or memory.
This is **same-reviewer blinded repeat review, not independent human review or inter-rater
reliability**. Primary explanations agreed on 37/37 pairs per mode. Any classification differed
on 1/37 per mode; explicit adjudication resolved that field-role difference. Across 74 mode
observations, 66 agreements were confirmed, two disagreements resolved and six observations
retained uncertain. No observation was left uninspected or unadjudicated.

| Primary explanation | End-to-end / 37 | Precomputed OCR / 37 |
| --- | ---: | ---: |
| Token loss | 7 | 0 |
| Unsupported labels | 1 | 1 |
| Geometry | 3 | 1 |
| Missing or ambiguous financial roles | 13 | 17 |
| No genuine item table | 7 | 7 |
| Not visually an invoice | 1 | 1 |
| Clear printed roles | 2 | 7 |
| Unresolved evidence | 3 | 3 |

There are **33 actual header misses end-to-end and 27 precomputed**, so primary uncertainty
among misses is **3/33 and 3/27**, respectively, rather than 3/37. Visually confirmed invoice
miss denominators are **30 and 24**. Unknown or competing printed financial roles occur in
24/37 groups per mode; this is distinct from the three unresolved primary explanations.
Header detection changes on 6/37 pairs, all from end-to-end miss to precomputed detection;
27/37 miss in both modes and 4/37 detect in both. Primary explanation changes across modes
on 9/37 pairs; source-visible role classifications change on 0/37 for each of the four roles.
Better token availability does not resolve source financial semantics. Detected controls are
included in the 37-group tables but excluded from the invoice-miss decision denominator.

The decision gate was specified before final aggregation: complete adjudication, at least eight
and a strict majority in the same supported category among visually confirmed invoice misses
in **each** mode. A label/geometry majority would additionally need a repeated financially
explicit pattern; category counts alone cannot justify an alias or layout rule. The report
contains the full category-to-potential-implementation decision matrix.

**Final gate choice: no-go for a new extraction implementation from this sample.** Financial-role
ambiguity leads at **11/30 end-to-end** and **14/24 precomputed invoice misses**, but does not
clear the shared majority gate. Token loss, geometry, summary/list structures and uncertainty
remain mixed. This is the last diagnostic gate for this slice, not a prescription for more
alias experiments or an automatic vision pilot. Preserve the existing financial-role abstention
and production boundaries. No coverage gain, causal explanation for all misses or population
prevalence estimate is claimed. No parser, worker, matching, review, risk, canonical-record or
payment changes were made.

The first private inventory and its selected source assets were reused read-only. Only newly
selected documents needed OCR preparation, which ran in the guarded network-disabled evaluator
container. Historical header flags remain the frozen inventory's observations; no official
scoring or all-500 OCR rerun was needed. Host Tesseract/TESSDATA_PREFIX smoke limitations remain
documented and are not a commit blocker for this container-backed audit. Private assets, two
passes, mappings, labels and adjudication notes stay in ignored guarded scratch; only allowlisted
aggregates are exported to the fresh report directory.

Verification: focused financial-role/header-audit/coverage/table/parser tests passed (68 passed,
two Windows symlink-permission skips). The synthetic evaluation suite passed (91 passed, two
skips, three private-data tests deselected). Repository Ruff and strict mypy including the new
runner passed (122 source files). Privacy checks found none of the 500 manifest IDs or actual
private source locations in the seven changed files; private artifacts are ignored and untracked.
All 50 tracked historical report files match HEAD. The aggregate report exactly reproduces from
the private two-pass adjudication; schema and denominator checks passed. UTF-8/mojibake checks
passed on 43 Markdown files, including the fresh report, and git diff --check passed.
