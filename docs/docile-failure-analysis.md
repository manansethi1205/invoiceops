# DocILE aggregate failure analysis and targeted invoice fix

InvoiceOps separates document perception from deterministic arithmetic, matching, duplicate risk,
and human review. This work changes extraction evidence only. No policy or payment authorization
decision is delegated to extraction, and the candidate is not enabled in the production worker.

## Recovered baseline and dataset scope

The validation split loads **500 documents**. The original benchmark manifest selects 100 of them;
the original smoke manifest selects 10. Dataset size and evaluation sample size are separate
denominators. An environment variable pointing to the DocILE source checkout is not the dataset:
use the extracted directory containing `val.json`, PDF, OCR and annotation data.

The reports under `evals/reports/docile/0.2.0` and `0.2.0-smoke` are frozen.
Their JSON and Markdown bytes were checked against Git, and the 100-document baseline was
reproduced exactly using the original manifest SHA-256.

## Failure evidence on the fixed 100-document sample

The baseline emitted 72 KILE predictions end-to-end and 78 with precomputed OCR, but had no KILE
true positives. Of those unmatched predictions, 42 and 56 respectively geometrically overlapped
an annotation of the same class. Geometric overlap is a diagnostic, not DocILE's official
pseudo-character-center matching criterion.

Header rules attach entire label/value lines, sometimes both a label line and a value line.
Prediction conversion unions that evidence. A value at the right location can therefore receive
a box that also includes labels or unrelated text. Narrowing source evidence alone recovered
22 and 28 KILE true positives respectively, without changing extracted values or statuses.
This controlled comparison supports localization as one failure cause, not an explanation for
every failure.

Coverage is also poor. On the 100-document sample the baseline extracted only two invoice dates,
four/seven subtotals, and two tax values. Some extracted fields cannot be exported because their
evidence crosses pages. The sample contains 66 tax invoices and 34 other document types.
These observations prevent interpreting all errors as OCR or localization failures.

## Targeted implementation

`ValueGroundedInvoiceExtractor` is an opt-in
`deterministic-value-grounded@0.3.0` strategy layered over the unchanged
`deterministic-baseline@0.2.0`. It localizes invoice number, issue date, subtotal, tax and total:

- Search contiguous source-token spans inside the selected field's existing evidence.
- Require identifier normalization, date parsing or Decimal parsing to match its existing value.
- Choose a unique shortest span. Equally short competing locations or no matching span retain
  the original evidence.
- Preserve values, extraction statuses, currency, rule IDs and all line items.

Annotations are used only by the evaluator and aggregate diagnostics, never by the extractor.
This fix does not infer missing money, change priorities, expand labels, resolve business
ambiguity, or modify arithmetic, policy, risk or review transitions.

## Same-sample measured results

| OCR mode | Baseline supported KILE F1 | Candidate supported KILE F1 | Supported LIR F1, both |
|---|---:|---:|---:|
| End-to-end | 0.00% | 10.60% | 18.49% |
| Precomputed OCR | 0.00% | 13.30% | 22.28% |

The aggregate report is
[the 100-document comparison](../evals/reports/docile/value-grounded-0.3.0-analysis-100/report.md).
It includes official per-field TP/FP/FN counts. These F1 scores use official location matching,
not exact normalized-text correctness. JSON adds status, geometric-overlap, changed-evidence
and document-type counts. No raw predictions or evaluator matchings are written by this runner.

The evaluation container used docile-benchmark 0.3.5, PyMuPDF 1.28.2 and Tesseract 5.5.0.

## Full 500-document measured results

The separate full-split comparison evaluated all 500 documents in both OCR modes:

| OCR mode | Baseline supported KILE F1 | Candidate supported KILE F1 | Supported LIR F1, both |
|---|---:|---:|---:|
| End-to-end | 0.00% | 12.23% | 4.09% |
| Precomputed OCR | 0.00% | 14.38% | 5.18% |

See [the full validation report](../evals/reports/docile/value-grounded-0.3.0-analysis-500/report.md)
and its aggregate JSON. Header true positives increased from zero to 119/141;
false positives fell from 349/364 to 230/223, with prediction counts unchanged.
No supported header field lost true positives in this comparison.
Both variants preserved identical extracted values, statuses and line items on every document.

The full split exposes a substantial line-item coverage gap concealed by the smaller denominator:
end-to-end predictions include only 69 descriptions and 44 quantities against 1,836/1,576
annotations; precomputed OCR includes 93 descriptions and 50 quantities.
The supported LIR F1 is therefore much lower than the 100-document sample, even though this fix
leaves line items unchanged. Do not present the 100-document LIR result as full-validation
performance.

The localization gain extends to the complete split, but this is still a development comparison
containing the original sample, not an independent held-out test. Prioritize header label/value
coverage and positioned-table detection in separate versioned changes. Keep their before/after
reports distinct from these measurements.

## Verification and continuation

The local regression suite passed 408 tests with Docker/private-data markers excluded.
After strengthening exclusive report creation, the focused evaluation/localization suite passed
63 tests. Repository-wide Ruff and strict typing passed; the final report-helper changes also
passed strict typing. Original 100-document and smoke report bytes match Git, and all eight
official baseline F1/AP metrics reproduced exactly on the original 100-document manifest.

The production default remains frozen; adopting the candidate in worker/read paths would require
a separate rollout with strategy-selection and persisted-version tests. The current fix is
available directly as `ValueGroundedInvoiceExtractor` and through the comparison runner.

## Reproduction and report preservation

The analysis runner requires an explicit output directory and refuses any existing directory.
The original benchmark runner now also requires an explicit fresh output directory, and the
aggregate writer rejects an existing `report.json` or `report.md`.

With `DOCILE_DATASET_PATH` set to the extracted dataset, use the evaluation image containing the
current source:

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  -m scripts.analyze_docile_failures `
  --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/validation-500.json `
  --output-dir evals/reports/docile/value-grounded-0.3.0-analysis-500-new-run
```

Use `benchmark.json` and a different fresh output directory to reproduce the 100-document
comparison. `--mode precomputed_ocr` can run parsing diagnostics without a local Tesseract
installation. Omitting `--mode` requires Tesseract and evaluates both modes.

The new `validation-500.json` manifest contains every validation ID in sorted order; it performs
no sampling. The seed is retained only for compatibility with the existing manifest schema.

Synthetic tests cover same-line and next-line evidence, both text sources, each localized field,
missing/conflicting values, repeated locations, unmatched values, source-evidence boundaries,
value/line-item preservation, official denominator handling, diagnostic overlap, aggregate
privacy, and overwrite guards.

DocILE is external benchmark context. These are development measurements, not production
accuracy claims or an independent held-out acceptance test. Remaining label coverage, numeric
invoice identifiers, multi-panel headers, repeated/cross-page evidence, and net-versus-gross
semantics need separate fixes and measurements.
