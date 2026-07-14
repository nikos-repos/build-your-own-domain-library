---
name: domain-library-ingest-pipeline
description: |
  Entry point for a domain-library OCR-enabled book ingestion pipeline.
  The orchestrator owns OCR, fidelity reconstruction, source classification,
  indexing, specialist dispatch, merge, page creation, and audit gates.
triggers:
  - "ingest book into library"
  - "domain library pipeline"
  - "run library ingest"
  - "process book"
  - "book ingestion pipeline"
  - "/library-ingest"
  - "/ingest-book"
related_skills:
  - GLM-OCR
---

# Domain-Library Ingestion Pipeline Dispatcher Skill

## Scope

This skill is the dispatcher entry point for extracting source-grounded concepts from a published book into a domain-specific markdown Library.

The pipeline is designed for public, generalized use. It does not assume a specific subject domain, user name, local machine path, or proprietary project namespace. Implementations may rename scripts, lanes, and paths, but phase gates and evidence-hygiene rules should remain stable.

## Required arguments

| Argument   | Example                                        | Notes                             |
| ---------- | ---------------------------------------------- | --------------------------------- |
| `PDF_PATH` | `/path/to/domain-library/raw/dropbox/book.pdf` | Local path to the source PDF.     |
| `SLUG`     | `example-book-slug`                            | Lowercase hyphenated source slug. |
| `TITLE`    | `Example Book Title`                           | Optional book title.              |
| `AUTHOR`   | `Author Name`                                  | Optional author name.             |

## Repository assumptions

The dispatcher expects a Library repository with these conventional paths. Adapt the names if your implementation uses a different layout.

| Path                          | Purpose                                                                                 |
| ----------------------------- | --------------------------------------------------------------------------------------- |
| `raw/dropbox/`                | Incoming PDFs before ingestion.                                                         |
| `raw/papers/<slug>/`          | OCR output, reconstructed markdown, chapter files, images, and source reports.          |
| `raw/papers/<slug>/chapters/` | Canonical split chapter/unit markdown files.                                            |
| `_meta/extractions/<slug>/`   | Pipeline state, gates, specialist outputs, schema drafts, merge artifacts, and reports. |
| `_meta/scripts/`              | Phase runner scripts.                                                                   |
| `_meta/schemas/`              | Extraction JSON schemas and validators.                                                 |
| `concepts/`                   | Final PAGE_SCHEMA-compliant Library pages.                                              |
| `index.md`                    | Library index updated after page creation.                                              |
| `log.md`                      | Append-only ingestion/page-creation log.                                                |

Before work, read `_meta/contracts/PAGE_SCHEMA.md`, `index.md`, and recent `log.md` entries. Treat raw source files as immutable, search the local library before creating a duplicate concept, use only predicates declared in `_meta/contracts/VOCABULARY_GUIDE.md`, and let Phase 5 maintain `index.md` and `log.md` after page writes. These are the retained runtime rules from the retired `llm-wiki` skill.

## Naming schema

Extraction unit directories use `team-<unit_id>`, where `unit_id` is collision-safe: `ch08`, `ch08-part02`, or `ch00-part001`.

| Owner           | File                                 |
| --------------- | ------------------------------------ |
| Orchestrator    | `orchestrator-vision-enrichment.md`  |
| Orchestrator    | `orchestrator-source-index.md`       |
| `defs` lane     | `domaindefs-definitions.md`          |
| `math` lane     | `domainmath-formulas.md`             |
| `examples` lane | `domainexamples-examples.md`         |
| `warnings` lane | `domainwarnings-warnings.md`         |
| `context` lane  | `domaincontext-empirical-context.md` |
| Assembler       | `team-<unit_id>-presentation.md`     |

Native worker profile names may be prefixed by the project or domain, but generated files should remain stable and predictable.

## Vocabulary and page-schema requirements

All generated final concept pages must adhere to the public `_meta/contracts/PAGE_SCHEMA.md` and `_meta/contracts/VOCABULARY_GUIDE.md`.

Worker extraction drafts are intermediate artifacts. They do not need to be final PAGE_SCHEMA concept pages, but they must preserve evidence in a form that allows the page writer to create valid pages later.

## Active command table

The command names below use a neutral `library_` prefix. Replace this prefix with your project's actual runner names if needed, but do not bypass the phase gates.

| Phase | Owner                                | Command / action                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Canonical output                                                                                  | Gate                                                                                                                                                                                          |
| ----- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0     | Orchestrator                         | Load this skill and required support skills; read `index.md` and `log.md`; confirm `.gitignore` exists.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | Oriented session.                                                                                 | Required files and support skills found; `.gitignore` covers `.env`, `.obsidian/`, `__pycache__/`, `*:Zone.Identifier`, temporary chunk dirs, and test-output dirs.                           |
| 1     | Orchestrator                         | Run OCR through the generic Phase 1 runner: `python3 _meta/scripts/library_phase1_ocr.py --slug "$SLUG" --pdf "$PDF_PATH" --title "$TITLE" --author "$AUTHOR"`. The runner should split oversized PDFs according to provider limits, reject invalid resume JSON, materialize remote OCR crop/image URLs locally, rewrite OCR JSON to local image paths, and write `combined.json`, `book.md`, and a Phase 1 gate.                                                                                                                                                                                              | API JSON, markdown, local image assets, Phase 1 gate.                                             | JSON is valid OCR output; all image URLs are materialized locally; gate status is `PASS`.                                                                                                     |
| 1.5   | Orchestrator                         | Resolve OCR paths and run fidelity reconstruction: `fidelity_reconstructor.py --min-fidelity 0.95 --require-images --stats-json _meta/extractions/$SLUG/gates/phase-1.5-stats.json`. Manual reruns must resolve paths through the configured resolver and must not hardcode OCR JSON/image locations.                                                                                                                                                                                                                                                                                                          | `book_fidelity.md` and Phase 1.5 gate.                                                            | Fidelity ≥95%; zero missing local images; gate status is `PASS`; `pipeline-state.json` marks Phases 1 and 1.5 complete.                                                                       |
| 2.1 + 2.2 | Orchestrator                      | Run `python3 _meta/scripts/library_phase2_chapters.py --slug "$SLUG"` once. It detects boundaries from `book_fidelity.md`, writes `chapters/*.md` and canonical `manifest.json`, validates extraction units, and advances state to `READY_FOR_2.3`. If auto-detection under-splits or fails, create `raw/papers/$SLUG/chapter-boundaries.json` with explicit TOC-derived `line_start` entries and rerun. Fixed-size fallback chunks are forbidden; a non-empty `chapters/` requires explicit `--force`. | `chapter-boundaries.json` when needed, `chapters/*.md`, `manifest.json`, and Phase 2.1 + 2.2 gates. | One runner writes both gates; boundary detection, units, and manifest must all validate. |
| 2.3   | Orchestrator                         | Run block annotation: `python3 _meta/scripts/library_phase23_blocks.py --slug "$SLUG"`. The runner must require Phase 2.2 `PASS`, load canonical `manifest.json`, reject fallback part files, fail on wrong-slug/malformed/duplicate/mismatched block IDs, annotate substantive body lines idempotently, and update state to `READY_FOR_2.4`.                                                                                                                                                                                                                                                                  | Inline block IDs, block-annotation report, Phase 2.3 gate.                                        | Every substantive manifest file has same-slug block IDs; no wrong, duplicate, or mismatched IDs; no fallback chunks.                                                                          |
| 2.4   | Orchestrator                         | Resolve and rebase chapter image references: `python3 _meta/scripts/library_phase24_images.py --slug "$SLUG"`. The runner must require Phase 2.3 `PASS`, resolve OCR paths through the configured resolver, copy/rebase image refs into `raw/papers/$SLUG/chapters/images/`, forbid remote/data image refs, and update state to `READY_FOR_3.0`.                                                                                                                                                                                                                                                               | Local chapter image refs, image-reference report, Phase 2.4 gate.                                 | Zero missing refs; zero remote/data refs; OCR-image books have at least one resolved local image ref when images exist.                                                                       |
| 3.0   | Orchestrator                         | Run vision enrichment: `python3 _meta/scripts/library_phase30_vision.py --slug "$SLUG"`. The runner must require Phase 2.4 `PASS`, verify chapter images remain local/resolved, discover extraction units, scan for unresolved `VISION_*_NEEDED` markers, write one `orchestrator-vision-enrichment.md` per unit, and update state to `READY_FOR_3.1`.                                                                                                                                                                                                                                                         | Per-unit vision logs, vision report, Phase 3.0 gate.                                              | No unresolved vision markers; every unit has a vision log; local image manifest recorded.                                                                                                     |
| 3.1   | Orchestrator                         | Build source indexes: `python3 _meta/scripts/library_phase31_source_index.py --slug "$SLUG"`. The runner must require Phase 3.0 `PASS`, discover extraction units, write deterministic source indexes with machine-readable hidden JSON, validate exact one-to-one block coverage, and update state to `READY_FOR_3.2`.                                                                                                                                                                                                                                                                                        | Per-unit `orchestrator-source-index.md`, source-index report, Phase 3.1 gate.                     | Every same-slug chapter block ID appears exactly once in the unit source index; no extras, duplicates, wrong-slug IDs, or invalid categories.                                                 |
| 3.2   | Orchestrator                         | Enforce unit size policy: `python3 _meta/scripts/library_phase32_size_split.py --slug "$SLUG"`. The runner must require Phase 3.1 `PASS`, enforce the canonical size policy, no-op already-small units, split oversized unsplit units into collision-safe parts when needed, archive superseded pre-split team dirs, regenerate per-current-unit vision/source-index artifacts, and update state to `READY_FOR_3.3`.                                                                                                                                                                                           | Part-safe current units and size-split report.                                                    | Zero unit collisions; no active unit exceeds the size threshold; no duplicated block IDs; source indexes and vision logs exist for current units.                                             |
| 3.3   | Orchestrator + native subagents      | Run `python3 _meta/scripts/library_phase33_dispatch.py --slug "$SLUG" --prepare`, then use the current runtime's native subagent mechanism for every generated assignment. Write `dispatch-result.json` with actual runtime, model, runtime task ID, and job ID, then run `--record`.                                                                                                                                                                                                                                                                                                                          | Runtime-neutral dispatch plan/report and verified job metadata.                                   | Every planned task ran, both expected files exist, identifiers are real, and Phase 3.3 is `PASS`.                                                                                             |
| 3.4   | Orchestrator                         | Verify specialist outputs: `python3 _meta/scripts/library_phase34_verify.py --slug "$SLUG"`. The runner must require Phase 3.3 `PASS`, verify lane markdown/schema outputs, reject missing sections, placeholder/slop text, invalid schema JSON, wrong/out-of-unit block IDs, and evidence-hygiene defects. Write verification/schema reports and a machine-owned validation marker, then advance state to `READY_FOR_3.5`.                                                                                                                                                                                    | Verification report, schema validation marker, pipeline-run manifest.                             | All named outputs exist, are non-empty, cite valid same-unit block IDs, pass schema validation, and have zero evidence-hygiene defects.                                                       |
| 3.5   | Orchestrator                         | Assemble team presentations: `python3 _meta/scripts/library_phase35_presentations.py --slug "$SLUG"`. The runner must require Phase 3.4 `PASS`, assemble every current `team-<unit_id>-presentation.md` from verified named-lane markdown, validate the assembled presentation, write presentation reports/audits, update the run manifest, write the Phase 3.5 gate, and advance state to `READY_FOR_4`.                                                                                                                                                                                                      | One validated `team-<unit_id>-presentation.md` per current unit plus presentation/audit reports.  | Required sections present exactly once; every section cites same-unit block IDs; enough embeds and substantial source quotes; no placeholders/slop.                                           |
| 4     | Orchestrator + human confirmation    | Prepare merge and scoring: `python3 _meta/scripts/library_phase4_merge_score.py --slug "$SLUG" --prepare`. The runner must require Phase 3.5 `PASS`, validate schema markers/reports, merge schema JSON drafts, score concepts, filter artifacts, validate block IDs, and write candidate/rationale packets. After a human reviewer chooses slugs, write `phase4-user-selection.json` and run `python3 _meta/scripts/library_phase4_merge_score.py --slug "$SLUG" --confirm --selection _meta/extractions/$SLUG/phase4-user-selection.json`. Only then does Phase 4 write `PASS` and advance to `READY_FOR_5`. | Scored concepts, cleaned candidates, rationale packet, confirmation JSON, confirmed concept list. | Zero dead block IDs; rationale packet keeps all scored concepts visible; non-empty human-confirmed selected slugs; no silent concept discard.                                                 |
| 5     | Orchestrator / canonical page writer | Create final pages: `python3 _meta/scripts/library_phase5_pages.py --slug "$SLUG"`. The runner must require Phase 4 confirmation `PASS`, confirmed concepts, Phase 3.5 presentation `PASS`, and active chapter block IDs. It creates pages only for human-confirmed concepts and only from validated team presentations, writes pages under `concepts/`, refuses to overwrite existing pages unless `--force`, updates `index.md` and `log.md`, writes page-build reports/gates, and advances state to `READY_FOR_POST`.                                                                                       | Source-grounded concept pages and page-build report.                                              | Pages are generated from team presentations, not scored metadata alone; YAML parses; block IDs exist in presentations and chapters; final pages comply with PAGE_SCHEMA and VOCABULARY_GUIDE. |
| Post  | Orchestrator                         | Run `python3 _meta/scripts/library_audit.py --slug "$SLUG" --wiki "$WIKI_PATH" --report _meta/reports/audit-$SLUG.json`. The command owns grounding QA, audit, the post gate, and the `DONE` transition.                                                                                                                                                                                                                                                                                                                                                                                                       | Grounding reports, final audit JSON, post gate.                                                   | Audit exits 0 and state is `DONE`.                                                                                                                                                            |

## Team Extraction Outputs

Worker extraction drafts are intermediate artifacts. They do not need to be final PAGE_SCHEMA adherent concept pages, but they must preserve evidence in a form that allows the page writer to create valid pages later.

## Final concept-page requirements

Final concept pages must include, at minimum:

- PAGE_SCHEMA YAML frontmatter.
- Top classification predicate block immediately after frontmatter.
- H1 title.
- Source-grounded sections appropriate to the page type.
- `## Author's Words` when direct source quotes are available.
- `## Relations` at the bottom for provenance, structural, lifecycle, and generative predicates.
- `## Evidence index` or equivalent evidence inventory.
- At least two block embeds when sufficient source evidence exists.
- At least two substantial direct quotes when available.
- `extracted_from::[source]` for direct book-derived pages.
- Deterministic YAML serialization with `quality_notes`.

All generated final concept pages must adhere to the `_meta/contracts/PAGE_SCHEMA.md` and `_meta/contracts/VOCABULARY_GUIDE.md`.

## Hard red lines

1. Do not run book-specific one-off phase scripts from the live script namespace; use the canonical phase runners.
2. Do not split chapters from raw OCR markdown; split only from the fidelity-reconstructed markdown.
3. Do not use fixed-size fallback chunks in the canonical path.
4. Do not run lower-level helper scripts as phase gates; use phase runners that write gates and advance state.
5. Do not hardcode local user paths, OCR output paths, or image locations.
6. Do not proceed while required gates are missing or not `PASS`.
7. Do not dispatch specialists for orchestrator-owned vision/source-index outputs.
8. Do not split oversized units with overlap; duplicated lines duplicate block IDs.
9. Do not mark dispatch `PASS` from a prepare-only plan.
10. Do not dispatch through a generic catch-all agent profile when named lane profiles are required.
11. Do not record `PASS` from synthetic job IDs or planned model strings alone; record actual routing/job metadata.
12. Do not dispatch specialists without the evidence-hygiene contract in their generated assignments.
13. Do not use undeclared predicates. Avoid generic `relates_to::` when a more specific declared predicate fits. Never use stale `related_to::`.
14. Do not write or keep validation markers by hand; they are valid only when machine-written by the verifier after schema validation `PASS`.
15. Do not make Phase 3.4 depend on assembled team presentations; presentations are assembled and validated in Phase 3.5.
16. Do not treat Phase 4 prepare as `PASS`; it is only `AWAITING_USER_CONFIRMATION` until confirmed by a human reviewer.
17. Do not use direct orchestrator-generated concept pages as a substitute for schema-valid specialist extraction JSON, scoring, confirmation, and presentations.
18. Do not overwrite existing concept pages unless `--force` is explicitly chosen for intentional replacement.
19. Do not use unstable `agent-N` naming in new outputs.
20. Do not run specialists without `orchestrator-source-index.md` for the unit.
21. Do not trust specialist/sub-agent completion without file verification.
22. Do not proceed with unresolved block IDs, unresolved local image refs, unresolved vision markers, or incomplete source-index coverage.
23. Do not create pages from scored metadata alone; pages come from validated team presentations.
24. Do not silently discard concepts; present sorted scored concepts and rationale to the human reviewer.
25. New source-grounded extraction pages use `extracted_from::`, not `derived_from::`.
26. Do not publish private raw files, proprietary source dumps, local paths, unpublished client/work material, secrets, tokens, or personally identifying data.

# 

## References

- `references/runbook-full.md` — deeper phase execution details.
- `references/phase-gates.md` — exact gates and failure actions.
- `references/specialist-dispatch-protocol.md` — named-lane specialist dispatch architecture.
- `references/naming-schema.md` — output, unit, and native-agent profile names.
- `references/test-suite.md` — executable tests.
- `_meta/contracts/PAGE_SCHEMA.md` — final page structure and evidence-link rules.
- `_meta/contracts/VOCABULARY_GUIDE.md` — controlled predicate vocabulary and wikilink rules.
