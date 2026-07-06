# build-your-own-domain-library

## Quant-Library

===============

Personal Library of quantitative-finance knowledge, built by ingesting books through a gated OCR → extraction → verification → publication pipeline facilitated by my OMP agent. Read in Obsidian (humans) or as plain markdown (agents).
Layout

| Path                                                   | Contents                                                                                                |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| `concepts/`                                            | Published concept pages (the product)                                                                   |
| `raw/papers/<slug>/`                                   | Per-book source: archived PDF, OCR output, `book_fidelity.md`, `chapters/*.md` with `^block-id` anchors |
| `_meta/scripts/`                                       | Pipeline phase runners, validators, QA tools                                                            |
| `_meta/extractions/<slug>/`                            | Per-book pipeline state, gates, specialist outputs                                                      |
| `_meta/prompts/`, `_meta/schemas/`, `_meta/contracts/` | Lane prompts, extraction schema, form contracts                                                         |
| `PAGE_SCHEMA.md`                                       | Wiki page contract (frontmatter, predicates, embed conventions)                                         |
| `index.md`, `log.md`                                   | Catalog + append-only action log                                                                        |

Setup
-----

    python3 -m venv .venv-pdf.venv-pdf/bin/pip install -r requirements.txt.venv-pdf/bin/python3 _meta/scripts/quantlib_pipeline_smoke_tests.py   # 53 tests, all must pass

Running the pipeline
--------------------

The operating contract (per-phase commands, gates, red lines) is `~/.omp/skills/quantlib-ingest-pipeline/SKILL.md`. Every phase writes a gate JSON under `_meta/extractions/<slug>/gates/` and fails closed. Phase 5 runs the smoke suite before publishing (`--skip-smoke` for emergencies only).

Useful tools:
    python3 _meta/scripts/wiki_integrity.py --wiki . --pages 'concepts/*.md'   # embed/link resolution report
    python3 _meta/scripts/rebuild_index.py                                     # regenerate index.md from concepts/
    python3 _meta/scripts/prune_raw.py --slug <slug> --apply                   # delete recreatable PDF chunks after fidelity PASS
    python3 _meta/scripts/quantlib_audit.py --slug <slug> --wiki . --report _meta/reports/audit-<slug>-$(date +%Y%m%d).json 
