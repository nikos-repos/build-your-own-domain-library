# Security

## Secrets

The only repository-owned secret is `ZHIPU_API_KEY` in the root `.env` (the
OCR client also reads `GLM_OCR_TIMEOUT` there). The `.env` file is gitignored
and `domain-library doctor` verifies that. Never commit a real key;
`.env.example` holds the placeholder form. If a secret does leak, rotate the
credential first, then clean history, and report the exposure privately to
the repository owner.

## OCR endpoint pinning

`glm_ocr_cli.py` sends the API key only to the fixed official Zhipu endpoint.
The endpoint is deliberately not configurable, so a malicious config or
environment variable cannot redirect your key to another host.

## Private source data

`raw/`, `_meta/extractions/`, `_meta/reports/`, and `concepts/` are gitignored
by default. Ingested books, OCR output, and generated pages never leave your
machine unless you deliberately commit them. Treat PDFs, OCR output, and
generated pages as potentially private: do not publish proprietary sources,
credentials, personal data, or absolute local paths. Red line 26 in the
ingest skill forbids publishing private raw files, secrets, or personal data.

## Pipeline integrity

Phase runners validate slugs and constrain generated paths. Do not bypass
those entry points with hand-written state, gates, or outputs.

## Reporting

Open a GitHub issue (omit sensitive details).
