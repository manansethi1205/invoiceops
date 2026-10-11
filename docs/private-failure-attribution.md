# Private deterministic failure attribution

This evaluation-only CLI reuses the human annotation contract, `EvaluationRunner`, native
`DocumentTextExtractor`, frozen `deterministic@0.2.0`, canonical normalization and the existing
DocILE `trace_line_parser`. It does not alter extraction, policy or production selection.
Single-process observation wraps the real header candidate resolver and money-label function,
delegating unchanged to them and restoring them on exit. Do not embed these process-wide hooks
or output suppression in a concurrent service. Tests verify unchanged extraction output.

## Definitions and uncertainty

Each header opportunity and each cell in a present annotated table receives one mutually
exclusive first-stage category. Tally denominators include all opportunities, broken down into
`present`, `absent`, and `not_annotated`; excluded unannotated labels are not accuracy failures.
The independent source/region/candidate signals use **present labels only** as denominator.
Explicit absence is evaluated separately. An absent cell in a missing or unassociated row is
`absence_unscorable`, not credited as a correct cell abstention. Failures retain opportunities.

The source probe uses the existing date, money and currency parsers and evaluator normalization
to find a unique minimal contiguous token span inside human evidence boxes. Nested spans around
one value are collapsed; repeated disjoint occurrences remain unresolved. Searches are bounded
to 32 tokens for descriptions and four for other fields. Cross-page spans and long/split values
may remain unresolved. `tokens_not_observed` means this bounded probe found no normalized match;
it is **not** proof that the original invoice lacks the value or that OCR lost it. A competing
span, oversized box or value found outside the labelled box is `annotation_or_tokens_unresolved`.
Currency codes, printed symbols, conversion conventions and unsupported wording can also defeat
this probe. Do not correct labels or add aliases based solely on this counter.

Header regions are existing label-pattern matches on the labelled page. Currency uses the
existing context pattern; this is a deliberately broad proxy. Table regions use existing table
headers on the labelled page. Neither establishes the correct region at the labelled value or
a root cause. Later pages can continue without a repeated header. The DocILE visual stages
(`before_header`, `probable_item`, rejection stages, etc.) are observations of the frozen parser.

Raw header candidates are observed before resolution, so a missing resolved total can have
competing candidates. Line-cell candidates here mean emitted nonmissing cells, with emitted
associated rows counted separately; pre-emission numeric alternatives are not instrumented.
No row is associated by index, arithmetic or value equality. A candidate must contain source
tokens from exactly one labelled row in its evidence, with exactly one candidate for that row.
Broad evidence, repeated tokens, merged rows and shared boxes can make this association
ambiguous. `detected_no_associated_row` can include an emitted row whose association is unsafe;
it is not necessarily an absent emitted row. Document-level no-emitted-row counters are separate.

`wrong_role` requires a different human-labelled role with a distinct value, equal to the
prediction, and source-location support. Wrong column semantics require the same proof within
a uniquely associated row. A displaced line-total span alone does not establish that its role
is gross, tax or net. Those competing roles are not independently labelled in this contract.
Zero confirmed column-role swaps therefore does not establish correct column semantics.
`wrong_row` requires source support in another annotated row; mixed anchors abstain instead.

`scorer_only` means a uniquely location-associated row is exact in all four canonical cells but
the existing order-preserving DP did not count it exact, for example reordered rows. The tool
does not assert that a nonmatching string is semantically correct, or infer a normalization
bug without such evidence. Source, role and schema uncertainty remain separate from scorer-only
attribution. Unsupported financial roles cannot be resolved from annotations or arithmetic alone.

The total/subtotal confusion counter has two explicit denominators: present totals and emitted
totals on those documents. Equal total/subtotal labels are counted separately and excluded from
confusion. Value equality and location-supported equality are separate counts. No arithmetic
reconstructs missing totals, tax, prices or quantities.

Layout families are closed structural proxies: `net_tax_gross_token_signature` means all three
words occur somewhere in the tokens; otherwise the family records detected-table status. These
are not visually confirmed independent layout families, and signatures can overlap the page's
table-header failure stage. Arbitrary private layout names/tags are never exported.

## Offline reproduction and privacy

Use a verified authorized corpus below ignored `work/real-invoice-private/`. Inputs and outputs
reuse the baseline's containment, Git-ignore/tracked-file, symlink/junction, duplicate-ID and
fresh-directory guards. The private diagnostics directory is required and must be new. Public
reports must be a fresh descendant of `evals/reports/real-input/`. No private IDs, values, text,
source paths, images, labels, candidate evidence or notes appear in public output or routine logs.
The private JSONL includes those sensitive traces; it is not suitable for Git or publication.

```powershell
$env:UV_OFFLINE = '1'
uv run python scripts/run_private_failure_attribution.py `
  --manifest work/real-invoice-private/corpus-03/manifest.jsonl `
  --output-dir evals/reports/real-input/failure-attribution-next `
  --private-diagnostics work/real-invoice-private/diagnostics/failure-attribution-next
```

Configure the existing Tesseract English runtime privately with process-local PATH and
TESSDATA_PREFIX. No installation, downloads, hybrid/provider imports or model calls are needed.
The measured run additionally blocked external SDK/client imports and Python socket/DNS calls.
Its corpus fingerprint uses the same document-plus-canonical-annotation algorithm as the
baseline. Revision/state identify the actual worktree at run time, not a future commit.

## Measured authorized sample

The [aggregate report](../evals/reports/real-input/failure-attribution-02/report.md) evaluates
29 documents / 29 pages without failures, with the same annotation-inclusive fingerprint as
the updated baseline. One document uses actual OCR. Human-reviewed AI-assisted labels, narrow
related tax-invoice layouts, zero present unit-price labels and the OCR case without positive
labels limit generalization. These are observed development measurements, not holdout results.

All 28 present totals are found in labelled source boxes. All have raw candidates: 14 resolve
to ambiguity and 14 emit values equal to distinct labelled subtotals (14/28 present; 14/14
emitted). Twelve have subtotal-location support; two remain value-only confusion signals.
All 28 present subtotals are found: 14 have a header-pattern region but no candidate, and
14 have no matching region. The sole present tax has a region but no emitted candidate.
Invoice number and date are source-supported correct on 28/28 present labels each.
Currency remains probe-limited: 14/28 have no bounded normalized match and 14/28 are unresolved,
despite five emitted values scoring correct in the baseline. This is not a confirmed OCR defect.

All 50 descriptions, 50 line totals and 21 present quantities are found inside labelled boxes.
Of 50 annotated rows: 17 have no detected header, 15 associate uniquely but have wrong values,
16 have ambiguous association, and two have a header but no uniquely associated candidate.
Of 22 predicted rows: 15 associate uniquely and seven are ambiguous. All 15 unique candidates
have displaced line-total evidence; no role swap to another independently labelled column is
confirmed (0/22). No scorer-only row failures are observed. At document level, 17/28 labelled
tables emit no rows and 15/28 have no detected header. These are distinct denominators.

For descriptions and line totals (50 opportunities each), the first-stage counts are 17 region
misses, 15 wrong values, 16 unresolved evidence associations and two unemitted candidates.
For quantities (21 present, 29 absent), present counts are one region miss, 11 unemitted cells
and nine unresolved associations; absent counts are four correct absences and 25 unscorable.
Unit prices have zero present labels, 15 correct associated absences and 35 unscorable absences.
The family slices are 14 token-signature documents with 36 rows and 15 no-detected-table
documents with 14 rows (the latter includes the unlabelled OCR control).

The next safely actionable parser experiment is a **bounded financial-summary role guard**:
abstain from assigning a generic Total candidate when multiple net/tax/gross amount roles
cannot be uniquely bound to the intended total. The 14/14 emitted-total confusion pattern
supports this safety priority. Test explicit unambiguous single-value totals, tax/subtotal
exclusions, multiple amounts, wrapped labels and repeated summaries in a separate versioned
slice. Do not add broad table aliases or infer missing financial values. This audit implements
neither the guard nor any production change, and makes no automatic-payment safety claim.
