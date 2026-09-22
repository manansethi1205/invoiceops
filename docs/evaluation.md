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

## Hybrid replay and guarded live mode

The synthetic stress set covers unseen layouts, OCR/scanned and rotated sources, distracting
totals, duplicate quotes, missing fields, arithmetic inconsistency, embedded prompt injection,
multiple pages, and provider failure. Replay uses production routing, grounding, fusion, and
repository-owned schemas without network access:

```powershell
uv run python scripts/run_hybrid_evaluation.py --mode hybrid-replay `
  --output-dir evals/reports/hybrid/0.3.0-replay
```

The report separates 0.2.0 deterministic metrics from 0.3.0 replay metrics and includes header
exact accuracy, exact line F1, schema validity, coverage, grounding, agreement, disagreement
abstention, invocation/provider-failure rates, latency, and tokens. Cost stays `null` unless both
token prices are supplied. `hybrid-live` refuses to run without `--allow-live` and
organization-owned manifest wiring; it is excluded from ordinary tests and CI.

## Reproducible OCR runtime

An OCR-tagged manifest is rejected before document bytes are loaded unless the Tesseract runtime
passes its readiness check. Run the frozen holdout in the dedicated container:

```powershell
docker compose --profile evaluation run --rm evaluator `
  --manifest evals/manifests/holdout.jsonl `
  --output-dir evals/reports/synthetic/0.2.0-container `
  --allow-holdout
```

The container report records the Docker runtime, Tesseract version, `eng` language and 200 DPI.
It is separate from the earlier local environment-failure report, and its dataset fingerprint must
match the frozen holdout fingerprint.

## DocILE external benchmark

Install evaluation-only tools with `uv sync --group evaluation`. Download `annotated-trainval`
outside source control and set `DOCILE_DATASET_PATH` to that directory. Never store its token in
`.env`, commands, logs or Git.

Profile aggregate label and document counts without printing field text:

```powershell
uv run --group evaluation python scripts/profile_docile_dataset.py `
  --dataset-path $env:DOCILE_DATASET_PATH `
  --output work/docile-profile.json
```

Generate deterministic ID-only manifests after inspecting that profile:

```powershell
uv run --group evaluation python scripts/create_docile_samples.py `
  --dataset-path $env:DOCILE_DATASET_PATH
```

Run the 10-document smoke sample in both end-to-end and precomputed-OCR modes. The Compose
evaluator bind-mounts the directory in `DOCILE_DATASET_PATH` read-only and supplies Tesseract:

```powershell
docker compose --profile evaluation run --rm --build --entrypoint python evaluator `
  scripts/run_docile_evaluation.py `
  --dataset-path /data/docile `
  --sample-manifest data/docile/manifests/smoke.json `
  --output-dir evals/reports/docile/0.2.0-smoke
```

Run this from the same PowerShell session in which `DOCILE_DATASET_PATH` points to the extracted
dataset. A direct Windows run deliberately fails its OCR-runtime preflight when Tesseract and its
English language data are unavailable.

Replace `smoke.json` with `benchmark.json` and the output directory with
`evals/reports/docile/0.2.0` for the fixed 100-document benchmark. The script invokes DocILE's
official `evaluate_dataset` implementation for KILE and LIR. Raw KILE/LIR prediction files remain
ignored. The committed report contains only aggregate supported-subset F1 and full official
F1/AP, with the two OCR modes kept separate.
