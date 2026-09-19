# Reproducible deterministic evaluation

The committed corpus is entirely synthetic. Generate it with:

```powershell
uv run python scripts/generate_synthetic_evaluation.py
```

Development evaluation is unguarded:

```powershell
uv run python -m invoiceops.evaluation --manifest evals/manifests/dev.jsonl --output-dir evals/reports/development
```

Holdout evaluation requires an explicit acknowledgement:

```powershell
uv run python -m invoiceops.evaluation --manifest evals/manifests/holdout.jsonl --output-dir evals/reports/holdout/0.2.0 --allow-holdout
```

Header coverage is `extracted / labeled`, conditional exact accuracy is
`correct / extracted`, and overall exact accuracy is `correct / labeled`.
Line items are aligned in reading order with dynamic programming before exact
item and field-level metrics are calculated. Every report records the exact
denominators and SHA-256 dataset fingerprint.

Reports contain normalized predictions and failure categories. They never
contain absolute paths, raw page text, evidence snippets, or stack traces.
Measured project results remain separate from external benchmark context.
