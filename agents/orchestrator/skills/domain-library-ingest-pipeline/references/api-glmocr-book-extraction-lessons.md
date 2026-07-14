# API GLM-OCR Book Extraction Lessons

Use this reference when ingesting long Domain Library books with the GLM-OCR API and creating extraction concept pages.

## Durable lessons

### 1. Split PDFs by both page count and byte size

GLM-OCR enforces both limits:

- `<=100` PDF pages per request
- PDF file size `<=50MB`; use `45MB` as a safety margin

Do not assume a small source PDF remains small after splitting. Prefer pypdf range writing and verify `stat().st_size < 50MB` before each OCR call.

### 2. Resume logic must reject failed JSON

A chunk JSON is complete only if:

- file exists
- JSON parses
- `ok == true`
- either `text` is non-empty or `layout_details` is present

Never skip an existing `ok:false` JSON. Delete/retry it.

### 3. Fidelity reconstructor must accept chunk-wrapper JSON

For long books, `combined.json` may be a wrapper:

```json
{
  "slug": "...",
  "source_pdf": "...",
  "page_count": 291,
  "chunks": [
    {"chunk_index": 1, "start_page": 1, "end_page": 100, "result": {"layout_details": [...]}}
  ],
  "failures": []
}
```

`fidelity_reconstructor.py` should flatten `chunks[*].result.layout_details` in page order before reconstruction.

### 4. Chapter splitter may need manual TOC-derived starts

Generic chapter splitting can under-split OCR books when the title page, contents, or headings use inconsistent OCR labels. If auto-split produces only a few giant chapters, inspect the reconstructed `book_fidelity.md` headings and write `raw/papers/<slug>/chapter-boundaries.json` with explicit `line_start` entries before block annotation. Fixed-size fallback is a FAIL gate, not an accepted semantic split.

### 4.1 Image refs must be local before vision/source indexing

Phase 2.4 uses `library_phase24_images.py`, not direct mapper/verifier calls. It rebases chapter markdown refs into central `chapters/images/`, forbids remote/data refs, and fails if OCR contains image assets but chapter markdown has no resolved local image refs.

### 5. Extraction page frontmatter standard

Concept extraction pages must use this frontmatter order and style:

```yaml
---
title: "Clean Semantic Title"
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: 0.5
last_reinforced: YYYY-MM-DD
tier: working
quality: 0.82
quality_notes: "single-source GLM-OCR extraction; source-grounded with block embeds"
scope: shared
author: orchestrator
---
```

Rules:

- Strip section numbering from `title` frontmatter (`"Econometrics of Transactions in Electronic Platforms"`, not `"4 Econometrics..."`).
- Keep the H1/section text free to include numbering if it helps source navigation.
- Classification predicates (`conforms_to::`, `has_status::`, `in_domain::`) belong in the body immediately after frontmatter, not inside YAML.

### 6. Audit marker files

Phase 4 writes `_meta/extractions/<slug>/_blockid_valid` only from `library_phase4_merge_score.py --prepare` after `blockid_validator.py` returns a non-empty `valid` report. Do not create this marker by hand.

### 7. Page depth / quote gates

Audit `PO-46` requires:

- at least 80 lines
- at least 2 block embeds
- at least 2 substantial `>` quote lines

For code-heavy R/computational sections, add an additional quote from nearby source blocks under `## Author's Words` rather than padding unrelated prose.
Phase 3.5 applies these depth checks at the team-presentation boundary before page creation: at least two block embeds and at least two substantial `Author's Words` quote lines per presentation.
Phase 5 enforces these checks in `library_phase5_pages.py`: generated concept pages must be at least 80 lines, include at least two block embeds, include at least two substantial `Author's Words` quote lines, and cite only block IDs present in Phase 3.5 team presentations and active chapters.



### 8. Schema validation boundary

`EX-10`  expects the Phase 3.4 runner to validate schema JSON drafts under `_meta/extractions/<slug>/schema/`, write `schema-validation-report.json`, and machine-write `_validation_passed`. Custom generated-page JSON artifacts remain invalid substitutes for schema-compatible specialist extraction JSON.
