# Native-OCR synthetic-local milestone

This is an input-stage comparison, not model accuracy. Both fresh runs use the same verified
16-invoice corpus, `label-guided-stub-v1`, intended in-memory PO fixtures, extractor versions,
matching-v3 and `synthetic-source-safety-v2`. No rules, policy thresholds or safety gates changed.
Existing reports remain frozen.

The corpus fingerprint is
`2936c05503d82bd66add5a380f480f39c2cfbedf27ca4e422d0e93b81941137e`:
16 documents, 17 pages and 32 labelled rows. PDFs contribute 14 documents/15 pages/28 rows;
PNGs contribute two documents/two pages/four rows.

The fresh reference report uses two label-derived scan-token substitutions and zero actual OCR
documents. The native report uses exactly two actual OCR documents and zero substitutions.
PDFs use native embedded text in both modes. The host Tesseract installation was absent from
PATH; process-local PATH/tessdata configuration made the installed runtime available without
installation or downloads. Readiness reports `tesseract v5.5.3.20260724` with English available.
Actual extraction uses PyMuPDF 1.28.2 integrated Tesseract. The report explicitly identifies the
CLI version's provenance (`runtime-cli`), backend and backend version; this is not a claim that
the integrated library has the CLI's version, which the PyMuPDF API does not expose.

Both ordinary CLI runs were executed behind a private guard rejecting OpenAI SDK imports,
real provider/HTTP client construction and Python socket connections. Live settings/pricing
access was forbidden too. The local oracle ran in process; no external provider was initialized.
API tokens and cost were zero. Missing OCR still fails closed, and neither byte verification nor
Git-based ignored/untracked scratch checks were bypassed. An available cached OCR container
lacked Git, so the native run instead used the working host runtime with the existing guards.

## Paired results

Every entry below is unchanged between the fresh scan-token reference and native-OCR run.
Missing candidate-only rows remain abstentions; they were not invented to improve recall.

| Input | Documents / labelled rows | Deterministic TP / FP / FN | Local hybrid TP / FP / FN | Deterministic review | Hybrid review / MATCHED |
| --- | ---: | ---: | ---: | ---: | ---: |
| PDF | 14 / 28 | 4 / 12 / 24 | 14 / 2 / 14 | 14/14 | 10/14 / 4/14 |
| PNG | 2 / 4 | 0 / 0 / 4 | 0 / 0 / 4 | 2/2 | 2/2 / 0/2 |
| All | 16 / 32 | 4 / 12 / 28 | 14 / 2 / 18 | 16/16 | 12/16 / 4/16 |

| Input | Association precision | Candidate-row coverage | Abstention | Unsafe financial promotions | Cross-row promotions | Hybrid false automatic matches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PDF | 16/16 | 16/28 | 12/28 | 0/26 | 0/12 | 0/10 |
| PNG | 0/0 (null) | 0/4 | 4/4 | 0/2 | 0/0 (null) | 0/2 |
| All | 16/16 | 16/32 | 16/32 | 0/28 | 0/12 | 0/12 |

Both runs have zero unscorable associations and zero unscorable promotions, including numeric
and line-cell subcounts, in each input stratum. Deterministic false automatic matches are
0/14 for PDFs and 0/2 for PNGs. False-match denominators are expected-review documents, not
candidate rows or all matched documents. Null promotion/precision rates indicate no eligible
observations, not proven perfect safety.

One grounding result changes: PNG grounded-value acceptance drops from 28/28 to 27/28,
while PDFs remain 188/188. Overall acceptance is 216/216 versus 215/216. One invoice-number
proposal is rejected with `VALUE_NOT_FOUND_IN_QUOTE` under native OCR. Value binding is not
relaxed to accept it; deterministic output is retained. Header exact-match counts, row metrics
and review decisions remain unchanged. This is a safely rejected proposal, not unscorable
promoted evidence or a confirmed unsafe promotion.

The result is null: real OCR does not change line coverage, association or review outcomes on
these two scans. The parser still emits no PNG item rows; the oracle's candidate-only rows
remain rejected. This is an observed stage, not a diagnosed header or token-loss root cause.
No parser change or live-provider rollout is justified by this comparison alone.

## Reports, metadata compatibility and reproduction

The fresh reports are `16-invoice-synthetic-local-reference-03` and
`16-invoice-synthetic-local-native-01` under the existing hybrid report directory. Each JSON
and Markdown report publishes only aggregate counts, with `metrics_by_input_type` alongside
development/reserved partition metrics. The fresh reference's aggregate safety/value/decision
counts reconcile to the frozen corrected local report.

Legacy reports without `metric_version` now load as `None`; loaders do not infer current scoring.
Fresh generation explicitly stamps v2. New OCR/input-type fields default to unknown/empty on
legacy input. Tests preserve other existing fields and verify per-input-type accounting.

With the installed OCR executable on PATH and its English tessdata configured privately, use
the existing CLI with a fresh output leaf:

```powershell
.\.venv\Scripts\python.exe scripts/run_hybrid_evaluation.py --mode synthetic-local --manifest work/hybrid-live-synthetic/corpus-20261011-run2/manifest.json --max-documents 16 --max-pages 17 --partition all --allow-holdout --local-source-mode native --output-dir evals/reports/hybrid/16-invoice-synthetic-local-native-02
```

The label-guided oracle still bypasses independent model perception, hallucinations and candidate
omissions. The supplied PO bypasses supplier/PO discovery. Two scans and these already inspected
synthetic families are development data, not a business holdout or evidence of population OCR
quality, model accuracy, live provider reliability or production payment safety.
