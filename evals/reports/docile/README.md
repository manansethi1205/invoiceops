# DocILE report policy

This directory may contain aggregate-only `report.json` and `report.md` outputs. Do not commit
DocILE documents, OCR, page images, prediction files, evaluator matchings, failure excerpts,
credentials, tokens or local paths.

No benchmark result is included until the private validation data has been evaluated in both
end-to-end and precomputed-OCR modes. Missing results must never be replaced with estimates.

Existing reports are frozen. Both DocILE runners require an explicit fresh output directory.
The value-grounded comparison reports are separate development measurements and do not replace
the original 100-document baseline. Dataset load counts and evaluated-document counts must remain
distinct. See docs/docile-failure-analysis.md for the method and reproduction commands.
