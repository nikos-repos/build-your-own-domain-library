# Phase Gates

## Gate summary

| Phase | Pass condition | Fail action |
|---|---|---|
| 0 | Required agent skills and files loaded; `.gitignore` safe | HALT and report missing item |
| 1 | `_meta/extractions/<slug>/gates/phase-1.json` status `PASS`; API OCR JSON is valid; all GLM crop/image URLs are local files under `glmocr_output/imgs/` | HALT; do not fallback to MinerU/self-hosted automatically; rerun generic Phase 1 runner |
| 1.5 | Resolver returns valid API JSON/images; `book_fidelity.md`; fidelity ≥95%; zero missing local images; `_meta/extractions/<slug>/gates/phase-1.5.json` status `PASS` | Fix OCR/output mapping or assets; rerun reconstruction; do not split chapters |
| 2.1 | `_meta/extractions/<slug>/gates/phase-2.1.json` status `PASS`; boundaries detected from `book_fidelity.md`; manual TOC boundaries captured in `chapter-boundaries.json` when needed; fallback chunking fails closed | Create/fix `chapter-boundaries.json`; do not split semantic chapters as fixed chunks |
| 2.2 | `_meta/extractions/<slug>/gates/phase-2.2.json` status `PASS`; `chapters/*.md` and canonical `manifest.json` exist; unit count matches manifest; no duplicate `extraction_units.py` unit IDs; no overwrite without `--force` | Fix chapter splitter/manifest/unit filenames before block annotation |
| 2.3 | `_meta/extractions/<slug>/gates/phase-2.3.json` status `PASS`; canonical `manifest.json` files all have same-slug inline block IDs after `library_phase23_blocks.py`; no wrong-slug, malformed, duplicate, or chapter-mismatched block IDs; no bare fallback chunks | Fix stale IDs/file namespace or rerun gated annotator; do not proceed to image mapping |
| 2.4 | `_meta/extractions/<slug>/gates/phase-2.4.json` status `PASS`; `raw/papers/<slug>/image-refs-report.json` status `PASS`; all chapter image refs are local and resolve under `chapters/images/`; zero remote/data refs; OCR-image books have at least one resolved local chapter image ref | Fix OCR image assets or markdown refs; do not proceed to vision/source indexing |
| 3.0 | `_meta/extractions/<slug>/gates/phase-3.0.json` status `PASS`; `raw/papers/<slug>/vision-enrichment-report.json` status `PASS`; every unit has `orchestrator-vision-enrichment.md`; no `VISION_*_NEEDED` marker is unresolved; image refs still local/resolved | Fill structured marker sections with real vision evidence or patch source chapters; do not fabricate or proceed to source indexing |
| 3.1 | `_meta/extractions/<slug>/gates/phase-3.1.json` status `PASS`; `raw/papers/<slug>/source-index-report.json` status `PASS`; each unit has `orchestrator-source-index.md` with hidden `source_index_json`; chapter block IDs and indexed block IDs are exact one-to-one | Fix deterministic classifier/indexer or stale block IDs before specialist dispatch |
| 3.2 | `_meta/extractions/<slug>/gates/phase-3.2.json` status `PASS`; `raw/papers/<slug>/size-split-report.json` status `PASS`; every active unit is ≤2000 lines; split overlap is `0`; unit rediscovery has no collisions; current units have regenerated/verified `orchestrator-vision-enrichment.md` and `orchestrator-source-index.md`; block IDs remain unique | Fix split boundaries, stale team dirs, inherited vision marker evidence, or duplicate block IDs before specialist dispatch |
| 3.3 | Gate and dispatch report are `PASS`; shipped prompt contracts validate; every planned unit/lane task records actual runtime, model, runtime task ID, and job ID; both declared outputs exist | Do not proceed from prepare-only plans, missing outputs, missing tasks, or synthetic identifiers |
| 3.4 | `_meta/extractions/<slug>/gates/phase-3.4.json` status `PASS`; `_meta/extractions/<slug>/specialist-verification.json` status `PASS`; `_meta/extractions/<slug>/schema-validation-report.json` is a non-empty `PASS`; `_validation_passed` is machine-written by `library_phase34_verify.py`; every recorded unit/lane markdown output exists, is non-empty, has required lane sections, cites only same-unit same-slug source-index block IDs, and has no evidence-hygiene defects (`related_to::`, bare block-evidence predicates without `#^`, bracketed block IDs, or malformed extra-bracket embeds); every recorded schema JSON validates; `pipeline-run-manifest.json` records dispatch and verification evidence; no presentation file is required yet | Reclaim/reassign/correction task; fix markdown/schema/evidence-hygiene outputs; never hand-write `_validation_passed`; do not merge incomplete unit |
| 3.5 | `_meta/extractions/<slug>/gates/phase-3.5.json` status `PASS`; `_meta/extractions/<slug>/presentation-report.json` status `PASS`; one `team-<unit_id>-presentation.md` exists per current unit; all required sections appear exactly once; every section cites same-unit source-index block IDs; each presentation has ≥2 block embeds and ≥2 substantial `Author's Words` quote lines; `pipeline-run-manifest.json` includes presentation outputs; `presentation-evidence-balance-audit.json` and `.md` exist and are linked from the report/gate/manifest | Fix lane markdown/source grounding and rerun `library_phase35_presentations.py`; use the evidence-balance audit as advisory repair guidance only; do not hand-assemble or proceed to merge/page phases |
| 4 | Prepare: `_meta/extractions/<slug>/gates/phase-4.json` status `AWAITING_USER_CONFIRMATION`, `phase4-scoring-report.json` status `AWAITING_USER_CONFIRMATION`, `master-scored.json`, `master-top-clean.json`, `concept-selection-candidates.md/json`, `concept-selection-rationale-packet.md/json`, `blockid-validation-report.json` valid, and `_blockid_valid` machine-written by `blockid_validator.py`. Rationale packet rows must cover every scored concept with supporting lanes, strongest block IDs, source-section diversity, duplicate/alias risks, and inclusion/exclusion reasons. Confirm: `phase-4.json` status `PASS`, `phase4-confirmation.json` status `PASS`, `master-confirmed.json` non-empty, and state `READY_FOR_5` | If prepare fails, fix schema JSON/block IDs/threshold/filtering/rationale generation; if confirmation is missing, present candidates and rationale packet to the human reviewer and record selected slugs; never proceed to Phase 5 from `AWAITING_USER_CONFIRMATION` |
| 5 | `_meta/extractions/<slug>/gates/phase-5.json` status `PASS`; `page-build-report.json` status `PASS`; one page exists for every user-confirmed concept; every page was generated by `library_phase5_pages.py` from Phase 3.5 team presentation evidence; YAML frontmatter parses and includes deterministic keys including `quality_notes`; pages contain `## Author's Words`, `## Source-grounded definition`, `## Specific Example`, `## Relations`, `## Evidence index`, ≥2 block embeds, ≥2 substantial quotes, and `extracted_from::` while avoiding `derived_from::`; all page block IDs occur in team presentations and active chapters | Fix confirmed concepts, team presentations, or page writer validation; do not use book-specific direct page builders or proceed to post audit |
| Post | `library_audit.py` exits 0 | Report failures; no completion claim |

## Claim confidence and span grounding

Each schema JSON claim has `confidence: EXTRACTED|INFERRED|AMBIGUOUS`.
`EXTRACTED` additionally carries a non-empty `quote_verbatim` copied from its
cited block. Phase 3.4 normalizes whitespace and markdown emphasis before
checking the span against the Phase 3.1 source index. It records every result
in `specialist-verification.json`; mismatches become `AMBIGUOUS`, while more
than 20% demotions among a lane's EXTRACTED claims fail the Phase 3.4 gate.
Phase 4 down-weights ambiguous claims and groups them in `Needs human eyes`.
Phase 5 renders a `⚠` marker for INFERRED claims.

## Gate lifecycle and safe invalidation

`PASS` gates may record `input_fingerprints`: deterministic SHA-256 digests of
the files a runner consumed. A runner may print `SKIP (unchanged)` only when
its current fingerprints exactly match its own `PASS` gate.

Use `domain-library rerun --slug "$SLUG" --from <phase> --yes` to mark the
selected phase and later existing gates `STALE`. It preserves every prior gate
object under `previous`, updates `pipeline-state.json` to the selected
`READY_FOR_<phase>` state, and never deletes artifacts. `domain-library next`
accepts `STALE` gates and prints the canonical rebuilding command. Never
hand-edit a gate or state file; `--force` belongs to individual runner
overwrite policy and is not required for metadata invalidation.

## Required smoke tests before approval install

```bash
python3 -m py_compile _meta/scripts/*.py
domain-library run library_pipeline_test_suite
```
