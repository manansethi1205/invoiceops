# Opt-in deterministic financial-summary role guard

`deterministic-financial-summary-guard@0.3.0` reuses the frozen
`deterministic-baseline@0.2.0` and changes only the returned total field. It is instantiated
explicitly by the paired evaluator, with no registration in worker factories or production
read-path preference. Historical runs, matching policy, review, canonical records and payments
are unchanged. This candidate does **not** fix hybrid/VLM header promotions; hybrid fusion
continues using its existing behavior.

## Source-only rule

The guard consults document tokens, visual rows, printed labels, page/source identity and
the baseline candidate's evidence. It never imports evaluation annotations, compares a total
to the extracted subtotal, reconstructs an amount arithmetically, or uses document/vendor IDs.

Missing and ambiguous baseline totals are preserved exactly. An emitted value must have one
unique, bounded source-money span inside its evidence; unbound or repeated spans abstain.
Complete spans use the existing money parser, including up to four physically adjacent split
tokens. Separate columns are not concatenated into a number. Clearly labelled grand/invoice
totals retain baseline behavior once uniquely source-bound; this is not a general financial-role
fix for those explicit rules.

For the generic Total rule, a visual row with a single amount remains usable. Multiple complete
monetary spans do not establish which amount has the invoice-total role, including repeated
amounts and rows whose role labels are unreadable or absent. A unique direct printed gross or
payable label immediately before the selected amount can support it; otherwise the candidate
returns `AMBIGUOUS` with bounded source evidence. The guard never chooses another amount by
column order or calculation. The direct-label proof permits only intervening `amount`/`total`
label tokens, with no intervening numeric cell. Nearby financial role labels provide evidence,
not an inferred column mapping. They are restricted to the same page, eight row-font heights,
and the amount-column horizontal region. Labels on another page cannot justify an amount.

The multi-amount abstention does not depend on nearby labels: a generic Total with several
amounts and no role labels still lacks unique support. Adjacent prose or tax amounts on another
row do not suppress an otherwise unique single Total. False abstention remains possible when
visual reconstruction merges unrelated columns or numbers. Evidence and row geometry therefore
need independent-layout validation before any rollout. Wrapped/split layouts outside the bounded
proof abstain instead of inventing a value.

## Paired evaluator and denominators

The evaluator uses the existing `EvaluationRunner`, private manifest/human-label contract,
native PDF/OCR extractor, source fingerprint and guarded report paths. The baseline performs
actual native extraction once; the candidate runner receives that identical cached source.
Human values are used solely by the scorer. No oracle token substitution, external SDK/provider
initialization, network call, supporting-record creation or payment action occurs.

Public output is aggregate-only JSON/Markdown. Private case results require an explicitly
requested fresh ignored directory. Both directories must be fresh; private source paths must
be ignored/untracked and contained, without symlinks/junctions. Existing baseline and attribution
reports are not rewritten. Ordinary tests use synthetic inputs only.

```powershell
$env:UV_OFFLINE = '1'
uv run python scripts/run_financial_summary_guard_evaluation.py `
  --manifest work/real-invoice-private/corpus-03/manifest.jsonl `
  --output-dir evals/reports/real-input/financial-summary-guard-next `
  --private-diagnostics work/real-invoice-private/diagnostics/financial-summary-guard-next
```

Configure the already-installed English/Tesseract runtime privately using process-local PATH
and TESSDATA_PREFIX. These commands do not install or download a runtime. The measured run also
blocked external SDK/client imports and Python socket/DNS calls.

Outcome denominators are present total labels: correct, wrong, ambiguous, missing and failed
present opportunities reconcile exactly. Explicitly absent labels and unannotated labels are
separate. Emitted-total precision uses correct/(correct+wrong); it is undefined if nothing is
emitted. Subtotal confusion is counted only for distinct, present expected total/subtotal values;
location-supported errors additionally require subtotal token/evidence support. Those labels
never enter the runtime guard. Non-total equality includes values, statuses and evidence.

Review workload here is the existing mandatory financial validation gate **before PO-specific
matching**. A failed gate necessarily requires review under existing policy, but passing it
does not establish `MATCHED`. The real corpus contains no authorized PO/receipt labels, so actual
PO discovery, matching decisions, review resolution and false automatic matches are not measured.
Synthetic tests separately prove that a complete matching control changes from `MATCHED` to
`NEEDS_REVIEW` when its total becomes missing or ambiguous under unchanged matching policy.

## Measured development result

The [fresh paired report](../evals/reports/real-input/financial-summary-guard-02/report.md)
evaluates 29 documents, 29 pages and one actual OCR document, with the same annotation-inclusive
fingerprint as the updated baseline. Source revision/state record the parent revision and
uncommitted implementation at execution time; do not relabel it as a later commit.

| Present-total outcome | Baseline | Candidate |
| --- | ---: | ---: |
| Correct | 0/28 | 0/28 |
| Wrong | 14/28 | 0/28 |
| Ambiguous | 14/28 | 28/28 |
| Missing | 0/28 | 0/28 |
| Failed | 0/28 | 0/28 |
| Emitted coverage | 14/28 | 0/28 |
| Subtotal-location-supported role errors | 12/28 | 0/28 |

The one explicitly absent total remains a correct missing abstention in both versions. The
14 original total/subtotal value-equality cases include 12 location-supported errors and two
value-only signals. Added abstentions are 14/14 previously emitted totals. Wrong-emission
precision is not improved to 100%: candidate precision is undefined because it emits nothing.
Correct-total recall remains zero. This meets the corpus's zero-wrong-emission criterion through
abstention, not recovered financial values.

All non-total fields, invoice numbers, dates and rows are identical on 29/29 paired documents.
The incomplete-total review gate changes from 15/29 to 29/29; mandatory financial review remains
29/29, with zero added mandatory-review documents. The synthetic single-total and explicit-total
controls remain usable. This is a local safety regression result, not production effectiveness.

Keep the candidate opt-in. The corpus consists of related observed development layouts with
human-reviewed AI-assisted labels, no present unit prices, and an OCR case without positive
header/row labels. It cannot establish diverse-layout recall, scan accuracy, supplier/PO
association or payment safety. The next validation gate is independently sourced, human-labelled
financial summaries including correct generic totals and unrelated neighboring numbers, with
false-abstention counts and exact emitted-total denominators. Production promotion and any
hybrid/VLM role-guard work require separate decisions.
