# Smoke Tests

The architecture includes executable smoke tests in:

```text
_meta/scripts/library_pipeline_test_suite.py
```

## Tests included

| Test                                                         | Protects against                                                                                                                                                                                           |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `test_resolver_api_layout`                                   | Phase 1.5/2.4 OCR path drift                                                                                                                                                                               |
| `test_resolver_detects_remote_crop_urls`                     | Phase 1 image-asset fail-open from GLM crop URLs stored in `content`                                                                                                                                       |
| `test_fidelity_requires_local_images`                        | Phase 1.5 false pass when image regions lack local files                                                                                                                                                   |
| `test_phase2_manual_boundaries_write_gates`                  | Phase 2.1/2.2 runner state/gates, canonical `chapter-boundaries.json`, and manifest/unit validation                                                                                                        |
| `test_chapter_splitter_rejects_fallback`                     | fixed-size semantic fallback cannot silently become accepted chapters                                                                                                                                      |
| `test_phase2_refuses_existing_chapters`                      | reruns cannot overwrite annotated chapter directories without explicit `--force`                                                                                                                           |
| `test_phase23_runner_writes_gate_and_report`                 | Phase 2.3 state/gate/report semantics and same-slug block coverage                                                                                                                                         |
| `test_phase23_rejects_wrong_slug_block_ids`                  | stale block IDs cannot be preserved or mixed into a new slug                                                                                                                                               |
| `test_phase23_rejects_fallback_chunks`                       | canonical Phase 2.3 rejects bare fallback `part-NNN.md` chunks                                                                                                                                             |
| `test_phase24_runner_copies_rewrites_and_gates`              | Phase 2.4 state/gate/report semantics and central `chapters/images` rebasing                                                                                                                               |
| `test_phase24_rejects_remote_refs`                           | remote/data image refs cannot advance to vision/source-index phases                                                                                                                                        |
| `test_phase24_requires_refs_when_ocr_has_images`             | OCR-image books cannot lose all image refs in chapter markdown                                                                                                                                             |
| `test_phase30_no_markers_writes_pass_logs`                   | Phase 3.0 no-marker books still get per-unit vision logs and hard gate/state                                                                                                                               |
| `test_phase30_unresolved_marker_fails`                       | `VISION_*_NEEDED` markers cannot advance without real structured resolution                                                                                                                                |
| `test_phase30_accepts_resolved_marker_log`                   | completed structured vision logs allow marker-bearing units to advance                                                                                                                                     |
| `test_phase31_writes_source_index_gate_and_json`             | Phase 3.1 state/gate/report semantics, Markdown index, hidden JSON, and category counts                                                                                                                    |
| `test_phase31_rejects_wrong_slug_blocks`                     | wrong-source block IDs cannot enter source indexes                                                                                                                                                         |
| `test_phase31_rejects_duplicate_block_ids`                   | source indexes require exact one-to-one block coverage                                                                                                                                                     |
| `test_phase31_supports_split_part_units`                     | split part units get their own source indexes                                                                                                                                                              |
| `test_phase32_noop_writes_gate`                              | Phase 3.2 no-op state/gate/report semantics for already-small units                                                                                                                                        |
| `test_phase32_splits_and_regenerates_indexes`                | oversized units split with zero overlap, stale team dirs archived, source indexes regenerated, and state advances                                                                                          |
| `test_phase32_inherits_resolved_vision_markers`              | post-split units preserve resolved vision evidence under new marker IDs                                                                                                                                    |
| `test_phase32_rejects_nested_oversized_parts`                | already-parted units cannot be recursively split into colliding unit IDs                                                                                                                                   |
| `test_phase33_prepare_writes_dispatch_payload`               | Phase 3.3 prepare emits `agent_invocations`, includes evidence-hygiene assignment text, and does not prematurely write a PASS gate                                                                         |
| `test_phase33_record_writes_gate_after_jobs_recorded`        | Phase 3.3 PASS requires recorded native runtime job ids for every unit/lane pair                                                                                                                           |
| `test_phase33_record_rejects_missing_job_ids`                | missing runtime job ids fail closed instead of advancing to verification                                                                                                                                   |
| `test_pipeline_manifest_consumes_runtime_dispatch`           | run manifest consumes runtime dispatch records and schema output paths                                                                                                                                     |
| `test_phase34_verifies_outputs_schema_and_manifest`          | Phase 3.4 verifies markdown/schema outputs, writes validation marker, manifest, gate, and state without presentation dependency                                                                            |
| `test_phase34_rejects_missing_markdown_output`               | missing lane markdown fails closed and removes/avoids `_validation_passed`                                                                                                                                 |
| `test_phase34_rejects_invalid_schema_output`                 | invalid schema JSON fails closed instead of writing validation marker                                                                                                                                      |
| `test_phase34_rejects_evidence_hygiene_defects`              | Phase 3.4 rejects `related_to::`, bare-slug evidence predicates, malformed embeds, and bracketed block IDs                                                                                                 |
| `test_phase35_assembles_and_gates_presentations`             | Phase 3.5 assembles validated team presentations, writes evidence-balance audit JSON/Markdown, links it from report/gate/manifest, updates manifest, writes gate, and advances state                       |
| `test_phase35_rejects_missing_presentation_section`          | presentation gate fails if assembled outputs omit required sections                                                                                                                                        |
| `test_phase35_rejects_insufficient_author_quotes`            | presentation gate enforces quote-depth instead of accepting thin summaries                                                                                                                                 |
| `test_phase4_prepare_scores_filters_and_awaits_confirmation` | Phase 4 prepare scores schema JSON, filters, validates block IDs, writes candidate and rationale packets, tolerates `-->` inside source-index block text, and does not write PASS before user confirmation |
| `test_phase4_confirm_writes_pass_gate`                       | Phase 4 confirmation records selected slugs, writes PASS, and advances to Phase 5                                                                                                                          |
| `test_phase4_rejects_dead_block_ids`                         | dead schema block IDs fail Phase 4 instead of reaching page creation                                                                                                                                       |
| `test_phase5_writes_pages_from_team_presentations`           | Phase 5 canonical writer creates YAML-valid source-grounded pages from confirmed concepts and team presentations                                                                                           |
| `test_phase5_requires_phase4_confirmation_pass`              | Phase 5 cannot run from Phase 4 prepare-only `AWAITING_USER_CONFIRMATION`                                                                                                                                  |
| `test_phase5_rejects_existing_page_without_force`            | Phase 5 refuses accidental overwrites unless explicitly forced                                                                                                                                             |
| `test_units_do_not_collapse_parts`                           | `ch08` / `ch08-part02` output collisions                                                                                                                                                                   |
| `test_block_annotator_scans_fallback_chunks`                 | fallback `part-NNN.md` files receiving no block IDs                                                                                                                                                        |
| `test_image_verifier_detects_missing`                        | false image gate from directory existence only                                                                                                                                                             |
| `test_phase33_prepare_rejects_missing_native_agent`          | dispatch prepare fails closed when a lane agent profile is missing/malformed                                                                                                                               |
| `test_phase33_record_accepts_alternate_runtime_shape`        | Runtime-specific result shapes normalize without hardcoded providers or tools                                                                                                                              |
| `test_phase33_record_rejects_synthetic_job_ids`              | fabricated job IDs cannot satisfy the dispatch gate                                                                                                                                                        |
| `test_phase35_rejects_dead_embed_target`                     | presentations with unresolvable block-embed targets fail closed                                                                                                                                            |
| `test_phase4_flags_duplicates_and_confirm_refuses`           | normalized-slug duplicate candidates are flagged and cannot be confirmed silently                                                                                                                          |
| `test_scoring_folds_plural_and_possessive_slug_variants`     | `gambler-s-ruin`/`arc-sine-laws`-style variants merge instead of fragmenting the graph                                                                                                                     |
| `test_integrity_resolves_ok_and_anchor_missing`              | `wiki_integrity` resolves valid embeds and detects missing anchors                                                                                                                                         |
| `test_integrity_detects_target_missing_and_ambiguous`        | dead and ambiguous embed targets are classified, not ignored                                                                                                                                               |
| `test_integrity_detects_malformed_forms`                     | template-literal/bracketed embed junk is classified `malformed`                                                                                                                                            |
| `test_integrity_suffix_match_and_basename`                   | vault path-suffix and unique-basename resolution semantics match Obsidian's                                                                                                                                |

## Commands

```bash
cd /path/to/build-your-own-domain-library
python3 -m py_compile _meta/scripts/*.py
python3 _meta/scripts/library_pipeline_test_suite.py
```

## Required before final completion on real ingest

```bash
python3 _meta/scripts/library_audit.py \
  --slug "$SLUG" \
  --wiki "$WIKI_PATH" \
  --report "_meta/reports/audit-$SLUG-$(date +%Y%m%d).json"
```

A failed final audit means the ingest is not complete.
