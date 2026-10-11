# Private financial-role challenge benchmark

The subsequent [0.4.0 candidate comparison](financial-role-guard-04.md) preserves this harness,
corpus and reports, and evaluates three strategies on identical frozen source tokens.

This evaluation compares frozen `deterministic-baseline@0.2.0` with the opt-in
`deterministic-financial-summary-guard@0.3.0` on identical native-extracted source tokens.
Neither strategy, production selection, hybrid fusion nor matching policy is changed.
There are no provider/client imports, model calls or supporting-record writes in this runner.

## Independent source annotation

Keep authorized documents, manifests, annotations and case results under ignored, untracked
`work/real-invoice-private/`. The JSONL manifest format is the existing
[private benchmark contract](private-real-invoice-benchmark.md): relative document and
ground-truth paths, unique document IDs, supported PDF/PNG/JPEG content types and one split.
Challenge cohorts are explicit; a manifest's `holdout` spelling does not establish independence.
The runner rejects duplicate source bytes, path traversal, linked paths and existing outputs.

Each ground-truth file uses this new **evaluation-only** envelope. This abbreviated example
shows a synthetic printed-role contract, not real data or a production Invoice schema:

```json
{
  "annotation_version": "financial-roles-v1",
  "provenance": "synthetic_contract",
  "labelled_without_predictions": true,
  "invoice": {"annotation_version": "human-invoice-v1", "provenance": "human"},
  "gross_invoice_total": {
    "amount": {"status": "present", "value": "120.00", "evidence": [
      {"page": 0, "bbox": {"x0": 0.6, "y0": 0.7, "x1": 0.8, "y1": 0.73}}
    ]},
    "printed_label": {"status": "present", "value": "Grand total", "evidence": [
      {"page": 0, "bbox": {"x0": 0.1, "y0": 0.7, "x1": 0.3, "y1": 0.73}}
    ]}
  }
}
```

For real documents the outer provenance must be `human`. The nested `invoice` preserves the
legacy six-field/line annotation contract; its labels are not used to infer the new roles.
For synthetic fixtures this compatibility container is not a claim that a person reviewed them.
`net_subtotal`, `gross_invoice_total` and `payable_balance` each use the same amount/printed-label
pair; `component_tax` and `unknown_or_ambiguous` are lists of such pairs, permitting multiple
printed taxes or competing explanations. An empty list makes no claim that taxes are absent.
Each scalar pair defaults to `not_annotated`; both members must have the same status. Explicit
`absent` requires no values or boxes. Present roles require independent label and amount boxes
on a common page. Boxes are normalized to the original page orientation, with zero-based pages.

Review original documents **before viewing predictions**. Record the actual printed label and
amount separately, including separate net/subtotal, each component tax, gross invoice total
and balance remaining after credits/payments. Never sum components, equate payable with gross,
or assign a role solely from matching numbers. If context does not uniquely support a role,
leave that role unannotated and record the observed amount/label under `unknown_or_ambiguous`.
If there is no printed label supporting a known role, do not manufacture one. Repeated roles
or unresolved evidence may remain unscorable. The independence flag is an attestation, not
proof of two reviewers or inter-rater agreement. Retain adjudication privately.

Legacy `human-invoice-v1` files still load for `observed_development`, with **all new roles
unannotated**. They are refused as new challenge labels. Legacy reports without this scorer's
metric version retain `None`; newly generated reports explicitly stamp `financial-role-challenge-v1`.

## Reproduction and privacy

Configure an installed English Tesseract runtime locally; no download is performed. Native
PDF text and real OCR fallback use the existing `ObservedTextExtractor` and `EvaluationRunner`.
The opt-in guard receives the exact same cached `DocumentText`, not label-derived tokens.
OCR failures remain failed documents in recall denominators; no synthetic token substitution
is used. Failures and case predictions are written only to fresh ignored private diagnostics.
CLI failures are sanitized. Public JSON/Markdown are closed-schema aggregates and must be under
`evals/reports/real-input/`; existing directories are refused.

For a newly authorized real corpus with independently completed role labels:

```powershell
$env:UV_OFFLINE = '1'
uv run python scripts/run_financial_role_challenge.py `
  --cohort new_authorized_challenge `
  --manifest work/real-invoice-private/authorized-role-challenge/manifest.jsonl `
  --observed-manifest work/real-invoice-private/corpus-03/manifest.jsonl `
  --output-dir evals/reports/real-input/financial-role-authorized-next `
  --private-diagnostics work/real-invoice-private/diagnostics/financial-role-authorized-next
```

The observed manifest is required for new challenges: overlapping source bytes are refused.
This guards known reuse, but byte differences, related templates or duplicated invoice contents
still need human dataset review. Do not claim an independent holdout based only on this check.
Use `--cohort observed_development` for old invoices and `--cohort synthetic_contract` only
for authored synthetic labels. There is no live-provider option.

The synthetic fixture factory `tests/evaluation/financial_role_fixtures.py` creates source bytes
and label boxes from authored printed content **before extraction**, not predictions. To recreate
it in a fresh checkout/private directory, run the factory first (it refuses an existing corpus),
then the same CLI with `--cohort synthetic_contract` and its returned manifest. PDF serialization
may include fresh internal IDs; source-byte fingerprints identify each generated corpus rather
than promising regeneration yields identical PDF bytes. Re-evaluation of unchanged files keeps
the same fingerprint. Source fingerprints include canonical annotations. Report provenance
records the execution revision and dirty state, not any later commit.

```powershell
uv run python -c "from pathlib import Path; from tests.evaluation.financial_role_fixtures import write_contract_corpus; write_contract_corpus(Path.cwd())"
uv run python scripts/run_financial_role_challenge.py `
  --cohort synthetic_contract `
  --manifest work/real-invoice-private/financial-role-contract/manifest.jsonl `
  --output-dir evals/reports/real-input/financial-role-synthetic-contract-next `
  --private-diagnostics work/real-invoice-private/diagnostics/financial-role-synthetic-contract-next
```

If the generated corpus already exists, skip generation and re-evaluate the unchanged files
with fresh output/diagnostics paths. This keeps the same corpus fingerprint.

## Definitions and measured synthetic result

The [native synthetic report](../evals/reports/real-input/financial-role-synthetic-contract-02/report.md)
contains 12 documents/pages: 11 PDFs and one PNG processed by actual Tesseract
`5.5.3.20260724`. There are 11 present gross-total labels and one unknown/unannotated target;
no failed documents. Cases cover generic, grand/gross, multi-column, repeated-value, unrelated
reference-number, wrapped-label, split-number, unknown-role and misleading payable layouts.
These are contract fixtures authored for this slice, **not independent real-world validation**.

| Metric | Baseline | Guard 0.3.0 |
| --- | ---: | ---: |
| Correct normalized gross value | 7/11 | 6/11 |
| Wrong normalized gross value | 3/11 | 1/11 |
| Ambiguous / missing | 0/11 / 1/11 | 3/11 / 1/11 |
| Emitted-total value precision | 7/10 | 6/7 |
| Correct-total value recall | 7/11 | 6/11 |
| Source-supported competing-role errors | 3/10 emissions | 1/7 emissions |
| Unresolved emitted evidence | 0/10 | 0/7 |
| Total-incomplete pre-PO gate | 2/12 | 5/12 |
| Mandatory financial-review gate | 12/12 | 12/12 |

Correct/wrong are normalized **value** outcomes; they alone do not prove the financial role.
Value precision divides correct by correct + wrong + emissions on explicitly absent targets.
Unannotated target emissions are excluded from value precision and shown separately. Recall
uses all present gross labels, including extraction failures. Role-supported precision divides
uniquely gross-supported correct emissions by **all** emissions. A competing-role error requires
the emitted amount to be source-bound to exactly one independently labelled net/tax/payable role,
with its printed label visible in source tokens, and not also bound to gross evidence. Equal
values across roles or evidence spanning several roles remain unresolved, not confirmed errors.
An unannotated gross target also leaves emitted role evidence unresolved.
The human role-to-label relation is trusted; the scorer does not independently visually verify it.

False abstentions are **1/7** source-supported correct baseline totals: an unrelated reference
number shares the visual Total row. The guard turns the baseline's correct total ambiguous.
One source-supported payable-balance error remains emitted via the frozen explicit `Amount due`
rule. This shows 0.3.0 is not a general gross-versus-payable role fix. Neither behavior was retuned.
All non-total outputs, including evidence and rows, remain identical on 12/12 pairs. Review
counts are existing pre-PO gates; no authorized PO/receipt corpus is available, so actual
matching decisions or payment authority are not evaluated. All fixtures lack a complete
matching contract, making mandatory-review counts deliberately nondiagnostic of operational load.
The native run blocked external SDK imports and Python socket/DNS calls: zero provider calls,
API tokens or cost. One scanned fixture cannot establish OCR accuracy across layouts.

The old [29-document paired result](../evals/reports/real-input/financial-summary-guard-02/report.md)
is frozen and separate: baseline 0 correct/14 wrong/14 ambiguous out of 28 present total labels;
guard 0 correct/0 wrong/28 ambiguous. Its reviewed total labels lack the new independent role
contract and cannot be silently reinterpreted as gross-role evidence. It is observed development
data comprising related layouts, not a holdout and not pooled into the synthetic denominators.

Keep 0.3.0 opt-in. The next validation milestone is authorized, independently labelled supplier
invoices from multiple issuers, explicitly separating invoice gross from payable balance and
including correct generic totals with neighboring reference numbers. This harness can measure
the two demonstrated boundaries without changing extraction. No production promotion is justified.
