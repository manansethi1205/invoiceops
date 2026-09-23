# Security policy

## Reporting

Do not open a public issue containing a vulnerability, credential, personal data, invoice, purchase
order, OCR output or other financial document content. Report security concerns privately to the
repository owner and include only the minimum synthetic reproduction needed to investigate.

## Data handling

- Use synthetic or explicitly de-identified fixtures only.
- Never commit financial documents, raw DocILE content, OCR text, API keys or production exports.
- Treat model and OCR document content as untrusted input; do not place it in logs.
- Local `.env` credentials and `X-Reviewer-ID` are development conveniences, not production
  security controls.

## Current boundaries

The review event hash chain provides application-level tamper evidence; it does not stop a database
administrator from rewriting records and hashes. `X-Reviewer-ID` is unverified and must be replaced
with authenticated organization identity and authorization before deployment. `ACCEPTED_EXCEPTION`
does not authorize payment. The project does not yet implement payment execution.
