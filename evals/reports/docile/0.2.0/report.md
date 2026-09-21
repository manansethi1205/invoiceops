# DocILE external baseline

## Method

- Extractor: `deterministic-baseline@0.2.0`
- Sample: fixed 100-document validation subset
- Sampling seed: 1205
- End-to-end OCR: PyMuPDF embedded text with Tesseract fallback
- Parsing-only OCR: DocILE precomputed OCR
- AP is uncalibrated because this deterministic baseline emits no confidence scores.
- A task with zero predictions is reported as zero for AP, precision, recall and F1; no placeholder predictions are introduced.

## Supported fields

KILE: document_id, date_issue, amount_total_net, amount_total_tax, amount_total_gross.

LIR: line_item_description, line_item_quantity.

## Results

| Mode | Metric | Result |
|---|---|---:|
| End-to-end | Supported-subset KILE F1 | 0.0000 |
| End-to-end | Supported-subset LIR F1 | 0.1849 |
| End-to-end | Official full KILE F1 | 0.0000 |
| End-to-end | Official full LIR F1 | 0.0670 |
| End-to-end | Official full KILE AP | 0.0000 |
| End-to-end | Official full LIR AP | 0.0270 |
| Precomputed OCR | Supported-subset KILE F1 | 0.0000 |
| Precomputed OCR | Supported-subset LIR F1 | 0.2228 |
| Precomputed OCR | Official full KILE F1 | 0.0000 |
| Precomputed OCR | Official full LIR F1 | 0.0816 |
| Precomputed OCR | Official full KILE AP | 0.0000 |
| Precomputed OCR | Official full LIR AP | 0.0351 |

## Interpretation

Supported-subset metrics cover only semantically mapped InvoiceOps fields. Full official metrics include every DocILE class and are expected to be lower.

## Limitations

The fixed sample is not the complete validation set. InvoiceOps does not encode gross-versus-net tax basis for line prices or amounts. Raw documents, OCR, predictions and evaluator matchings are deliberately excluded from this report.
