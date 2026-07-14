# Security

## Secrets

The only repository-owned secret is `ZHIPU_API_KEY` in the root `.env`. The
`.env` file is gitignored and `library.py doctor` verifies that. Never commit
a real key; `.env.example` holds the placeholder form.

## OCR endpoint pinning

`glm_ocr_cli.py` sends the API key only to the fixed official Zhipu endpoint.
The endpoint is deliberately not configurable, so a malicious config or
environment variable cannot redirect your key to another host.

## Private source data

`raw/`, `_meta/extractions/`, `_meta/reports/`, and `concepts/` are gitignored
by default. Ingested books, OCR output, and generated pages never leave your
machine unless you deliberately commit them. Red line 26 in the ingest skill
forbids publishing private raw files, secrets, or personal data.

## Reporting

Open a GitHub issue (omit sensitive details).


