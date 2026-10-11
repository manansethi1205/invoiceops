# Opt-in financial-role guard 0.4.0

`FinancialRoleGuardExtractor` is instantiated only by an explicit evaluator. It identifies itself
as `deterministic-financial-summary-guard@0.4.0` and reuses the frozen 0.2.0 baseline and 0.3.0
guard helpers without modifying either. Production strategy registration, hybrid fusion and
matching/payment policy remain unchanged. This is a deterministic development candidate, not
a hybrid header-promotion fix or a rollout.

## Source-only changes

Printed `Amount due`, `Total payable` and `Net payable` are payable-balance evidence. A generic
summary with an inline `Payable` label receives the same conservative treatment. A payable
candidate cannot establish gross invoice total through its value, equality with other extracted
fields, credits/prepayments or arithmetic. It becomes ambiguous unless exactly one independently
printed gross proof can be bound. Existing missing/ambiguous baseline totals remain unchanged.

Independent proof is a complete same-row label `Gross amount`, `Gross total`, `Gross invoice
total`, `Grand total` or `Invoice total`, followed by exactly one bounded source-money span.
The label/amount must share a source type and aligned vertical centers. The amount must be no
more than eight physical font heights after the label. Supporting boxes require positive area.
Proof must be on the payable candidate's
page and within twelve font heights vertically. Competing repeated proofs, or nearby gross
labels whose geometry/value cannot be resolved, abstain, even when amounts are equal. When a
proof succeeds, evidence comes from the independent gross region, not the payable region.
Other explicit or generic behavior stays under the frozen 0.3.0 checks.

The only reference exclusion is a right-hand region headed by exact `Reference`, optionally
followed by `ID`, `number` or `no`, then one ASCII digit-only identifier. Decimal/currency/sign
syntax, extra prose or multiple identifiers are not excluded. The region requires a gutter of
at least six physical font heights from the financial words, an identifier within four font
heights of its label, distinct source `(block, line)` provenance, one source type, and row-center
spread no greater than a quarter font height. The gutter must be empty across source rows
within four font heights vertically; financial role labels in the reference region veto it.
After removing that region, exactly one financial money span must remain, containing the
original uniquely evidence-bound candidate. The candidate never selects the reference value
or another column. Uncertain separation retains the frozen ambiguity.

Horizontal thresholds convert normalized y-height through the original page height/width;
normalized x and y distances are not treated as physically interchangeable. The proof is
deliberately narrow: OCR/merged line provenance, rotation, close reference numbers, references
on the left, wrapped gross labels and remote/multipage gross proofs may still abstain. A wide
gutter and printed label are source observations, not guarantees across unseen issuers.

## Paired three-version evaluation

`run_financial_role_versions.py` reuses `ManifestAdapter`, the existing human annotation loader,
`ObservedTextExtractor`, `EvaluationRunner`, cached source, both frozen scorers, and existing
ignored-private/fresh-public path guards. All three extractors receive identical native source
tokens; annotations only enter scoring. Private predictions require explicitly selected fresh
ignored diagnostics. Public output is closed-schema aggregate JSON/Markdown, with fingerprints,
source revision/state, extractor versions and OCR version. Existing directories are refused.

```powershell
$env:UV_OFFLINE = '1'
uv run python scripts/run_financial_role_versions.py `
  --cohort synthetic_contract `
  --manifest work/real-invoice-private/financial-role-contract/manifest.jsonl `
  --output-dir evals/reports/real-input/financial-role-versions-synthetic-next `
  --private-diagnostics work/real-invoice-private/diagnostics/financial-role-versions-synthetic-next
```

For the authorized frozen real-input regression, use `--cohort observed_development`, its
existing `corpus-03/manifest.jsonl`, and separate fresh output/diagnostics names. Configure the
installed English Tesseract runtime locally; no runtime download or network service is used.
The measured runs also blocked provider/client imports and Python sockets/DNS.

## Measured development regressions

The [12-case synthetic report](../evals/reports/real-input/financial-role-versions-synthetic-02/report.md)
uses the unchanged challenge fingerprint
`c8b3c057f30c194ee78109a9696b7d9373a1617c0bfae0406884a2b04c20e199`:
12 documents/pages, 11 PDFs and one actual OCR PNG, Tesseract `5.5.3.20260724`, no failures.
There are eleven present independently authored gross targets and one unannotated target.

| Metric | 0.2.0 | 0.3.0 | 0.4.0 |
| --- | ---: | ---: | ---: |
| Correct / wrong values | 7/11 / 3/11 | 6/11 / 1/11 | 9/11 / 0/11 |
| Ambiguous / missing | 0/11 / 1/11 | 3/11 / 1/11 | 1/11 / 1/11 |
| Emitted-value precision | 7/10 | 6/7 | 9/9 |
| Correct-value recall | 7/11 | 6/11 | 9/11 |
| Source-supported competing-role errors | 3/10 emitted | 1/7 emitted | 0/9 emitted |
| False abstentions on supported correct baseline totals | 0/7 | 1/7 | 0/7 |
| Total-incomplete pre-PO gate | 2/12 | 5/12 | 3/12 |

0.4.0 restores two emissions from five missing/ambiguous 0.3.0 outputs and corrects one
already-emitted payable-role error. It adds zero abstentions among seven 0.3.0 emissions and
one abstention among ten baseline emissions (a competing multi-column summary). All nine new
emissions have uniquely supported gross evidence; unresolved emitted evidence is 0/9.
Mandatory financial review remains 12/12 for all versions because the fixtures omit a complete
matching contract. These counts cannot predict operator workload or false automatic matches.

The [29-document observed report](../evals/reports/real-input/financial-role-versions-development-02/report.md)
uses the unchanged real-input fingerprint
`20adbcfa757d37ca3fc5df915d25ea0459c33e33f8752b2d407e6e665a6feaa9`:
29 PDFs/pages and one OCR document. On 28 present legacy total labels, baseline is 0 correct,
14 wrong and 14 ambiguous; both guards are 0 correct, 0 wrong and 28 ambiguous. The one
explicitly absent total stays missing. Subtotal-location-supported errors are baseline 12/14
wrong emissions, versus zero emissions for either guard. Emitted precision is undefined for
both guards; recall is 0/28. Mandatory financial review remains 29/29, and total-incomplete
gates are 15/29, 29/29 and 29/29. 0.4.0 adds no emissions or abstentions relative to 0.3.0.

The real-input labels do not have the independent printed-role contract. Their false-abstention
metric is explicitly unavailable, not silently assigned zero, and their role errors are the
existing subtotal-location subset. The old corpus and synthetic contracts are separate
observed development regressions, not independent holdouts. Non-total values/status/evidence
and row outputs are identical on 29/29 and 12/12 pairs. Historical reports are untouched.
Source metadata identifies the execution parent revision plus working-tree changes, not a
future commit. No provider initialization, API tokens or cost occurred.

Outcome counts reconcile to present labels, including failures. Precision is correct divided
by correct + wrong + emissions on explicitly absent labels; unannotated emissions are separate.
Role-supported precision uses all emissions. False abstentions require independently labelled,
source-supported correct baseline gross totals. `recovered_totals_vs_03` counts restored
**emissions**, not necessarily correct values; consult the separate correctness/role scores.
All review metrics are existing pre-PO financial validation gates, not actual PO matching.

Keep 0.4.0 opt-in regardless of these results. Authorization and independently labelled supplier
invoices from multiple issuers are still required for a separate generalization gate. No rules
were tuned to document IDs, fixture amounts, annotation roles or expected values at runtime.
