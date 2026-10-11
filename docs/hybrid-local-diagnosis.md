# Synthetic-local automatic-match scorer diagnosis

The original 16-invoice local report flagged four automatic matches. All four are confirmed
evaluation geometry false positives, not confirmed extraction or policy failures. Two occur
in the grid family and two in the explicit-financial-role family. Case-level traces of source
labels, baseline and candidate fields, grounding/fusion outcomes, ground truth, synthetic PO,
decision checks and original scorer failures remain in ignored private scratch. No case IDs,
quotes, values, images or individual prediction rows are published here.

## Confirmed decision path

For every flagged invoice, the six canonical header values and both complete item rows exactly
match the synthetic truth. The fixture does not require review. Matching uses the intended
per-case synthetic PO, with passing checks and no unresolved extraction-row issue. Normalization
does not substitute values and the automatic-match threshold is not the source of these flags.
The harness supplies a known PO directly; it does not evaluate supplier recognition or PO search.

Deterministic header evidence includes the printed label and amount. The local oracle proposes
the same amount with grounded value-specific evidence. On agreement, conservative fusion retains
the deterministic evidence. Its bounding-box center can lie in the label prefix, outside the
amount-only annotation, even though the amount annotation is contained in that evidence box.
The old role scorer required the evidence center inside the annotation and therefore reported
no source-role hit: four subtotal failures and two total failures across the four documents.
The amounts, rows and production decisions were correct; the evaluation's expected-review
classification was wrong.

The label-guided stub makes correct proposals using printed cell labels; this is an oracle
regression, not measured model accuracy. The annotation construction intentionally labels the
amount alone, while deterministic evidence can include its prefix. Both representations are
valid. Changing the corpus, supplying narrower fabricated production evidence or weakening
matching would hide the scoring defect rather than repair it.

## Bounded evaluation correction

`synthetic-source-safety-v2` accepts a source-role hit on the same page when either the evidence
center is contained in the annotation or the annotation center is contained in the evidence.
It collects all qualifying labels: competing financial roles, repeated amounts in other roles,
wrong rows/pages and boxes spanning multiple amounts remain unsafe. Mere edge overlap is
insufficient. Canonical value equality is checked separately; geometry never supplies a value
or infers a financial role from arithmetic.

Only evaluation scoring changes. Extractor versions, canonical invoice fields, candidate
grounding, conservative fusion/abstention, matching-v3, live authorization/budgets and corpus
byte verification remain unchanged. Newly generated reports identify the metric version;
the original report remains an immutable result of the earlier center-only scorer.

## Metric definitions and comparison

The row-association numerator counts accepted candidate-to-deterministic row mappings whose
source row identity agrees with the labels. Its precision denominator contains all accepted
associations, including unscorable ones. Coverage uses proposed candidate rows. These do not
test header roles, document completeness, supplier association or eligibility for automatic match.

False automatic matches count MATCHED documents that the independent source/value/role scorer
or fixture says require review. Their denominator is those expected-review documents, not
accepted associations, all matched documents or all candidate rows. The old scorer incorrectly
included the four correct matched invoices in that denominator. Correcting the scorer changes
it from 16 to 12 without changing any matching decision or extracted value.

| Aggregate | Original scorer | Corrected scorer |
| --- | ---: | ---: |
| Documents / pages / labelled rows | 16 / 17 / 32 | 16 / 17 / 32 |
| Deterministic line TP / FP / FN | 4 / 12 / 28 | 4 / 12 / 28 |
| Local hybrid line TP / FP / FN | 14 / 2 / 18 | 14 / 2 / 18 |
| Deterministic false automatic matches | 0/16 | 0/16 |
| Local hybrid false automatic matches | 4/16 | 0/12 |
| Local hybrid review / matched documents | 12 / 4 | 12 / 4 |
| Row-association precision | 16/16 | 16/16 |
| Candidate-row association coverage | 16/32 | 16/32 |
| Candidate-row abstention | 16/32 | 16/32 |
| Unsafe financial promotions | 0/28 | 0/28 |
| Cross-row promotions | 0/12 | 0/12 |

Both runs use the same verified manifest fingerprint and label-guided stub. PDF text is native;
the two scan inputs use explicitly declared label-derived token fixtures, not measured OCR.
External API calls, tokens and cost are zero. This comparison repairs a metric, not extraction
accuracy. Reserved synthetic layouts are observed development data after inspection, not an
independent business holdout, and no live-provider quality or production rollout is established.
