# Full Runbook

## Phase 0 — Orientation

1. Set:
   
   ```bash
   export WIKI_PATH=/path/to/build-your-own-domain-library
   ```

2. Run `domain-library doctor`, then load the ingest and GLM-OCR runtime skills.

3. Read: `_meta/contracts/PAGE_SCHEMA.md`, `_meta/contracts/graph-vocabulary-quickref.md`, `index.md`, `log.md`.

4. Confirm `.gitignore` covers `.env`, `.obsidian/`, `__pycache__/`, `*:Zone.Identifier`, `chunk*/`, `test*/`.

## Safe phase invalidation

When upstream inputs or a prior phase need rebuilding, invalidate metadata
first rather than deleting artifacts:

```bash
domain-library rerun --slug "$SLUG" --from 3.3 --yes
domain-library next --slug "$SLUG"
```

The command marks the selected phase and later existing gates `STALE`, stores
the old gate objects under `previous`, and returns pipeline state to the
selected phase. It does not delete inputs, reports, chapters, or pages.
Follow the `next` command; do not hand-edit state/gate JSON or add `--force`
unless a runner's documented overwrite policy is intentionally required.

## Phase 1 — API GLM-OCR

Use the `GLM-OCR` skill API path. Store output under:

```text
raw/papers/<slug>/glmocr_output/
```

Canonical preferred files:

```text
combined.json
book.md
imgs/ or images/ when the API returns assets
```

Canonical command:

```bash
domain-library run library_phase1_ocr \
  --slug "$SLUG" \
  --pdf "$PDF_PATH" \
  --title "$TITLE" \
  --author "$AUTHOR"
```

The runner writes `_meta/extractions/<slug>/gates/phase-1.json` and fails if any GLM crop/image URL is not downloaded and rewritten to a local `image_path`.

## Phase 1.5 — OCR resolver and fidelity reconstruction

`resolve_ocr_output.py` is the only source of OCR paths. Phase 1.5 and 2.4 must not hardcode OCR JSON/image paths. The Phase 1 runner executes this gate automatically; manual reruns use:

```bash
eval "$(domain-library run resolve_ocr_output --slug "$SLUG" --shell)"
domain-library run fidelity_reconstructor \
  --slug "$SLUG" \
  --input "$OCR_JSON" \
  --output "raw/papers/$SLUG/book_fidelity.md" \
  --images-dir "$OCR_IMAGES" \
  --min-fidelity 0.95 \
  --require-images \
  --stats-json "_meta/extractions/$SLUG/gates/phase-1.5-stats.json"
```

Pass requires `_meta/extractions/<slug>/gates/phase-1.5.json` and `pipeline-state.json` marking phases `1` and `1.5` complete.

## Phase 2 — Chapters, block IDs, images

Split from `book_fidelity.md`, never raw OCR markdown. Phase 2.1/2.2 is gated by:

```bash
domain-library run library_phase2_chapters --slug "$SLUG"
```

If automatic detection under-splits or fails, write `raw/papers/$SLUG/chapter-boundaries.json`:

```json
{
  "schema_version": 1,
  "slug": "<slug>",
  "expected_units": 3,
  "chapters": [
    {"chapter": 0, "kind": "frontmatter", "title": "Front Matter", "line_start": 1},
    {"chapter": 1, "title": "Chapter Title", "line_start": 120}
  ]
}
```

The runner fails fixed-size fallback, refuses to overwrite a non-empty `chapters/` unless `--force` is explicit, writes `manifest.json`, validates `extraction_units.py`, and records phase `2.1`/`2.2` gates.

Phase 2.3 is gated by:

```bash
domain-library run library_phase23_blocks --slug "$SLUG"
```

The Phase 2.3 runner requires Phase 2.2 `PASS`, rejects bare fallback chunks, fails on wrong-slug/malformed/duplicate/mismatched block IDs, annotates substantive body lines idempotently, writes `raw/papers/$SLUG/block_annotator-report.json`, writes `_meta/extractions/$SLUG/gates/phase-2.3.json`, and advances `pipeline-state.json` to `READY_FOR_2.4`.

Phase 2.4 is gated by:

```bash
domain-library run library_phase24_images --slug "$SLUG"
```

The Phase 2.4 runner requires Phase 2.3 `PASS`, resolves OCR paths through `resolve_ocr_output.py`, rebases chapter markdown refs into central `raw/papers/$SLUG/chapters/images/`, forbids remote/data refs, writes `raw/papers/$SLUG/image-refs-report.json`, writes `_meta/extractions/$SLUG/gates/phase-2.4.json`, and advances `pipeline-state.json` to `READY_FOR_3.0`.

## Phase 3 — Orchestrator then specialists

The orchestrator must produce these before specialist dispatch:

```text
_meta/extractions/<slug>/team-<unit_id>/orchestrator-vision-enrichment.md
_meta/extractions/<slug>/team-<unit_id>/orchestrator-source-index.md
```

Phase 3.0 vision enrichment is gated by:

```bash
domain-library run library_phase30_vision --slug "$SLUG"
```

The runner requires Phase 2.4 `PASS`, rechecks local image refs, scans chapters for `VISION_*_NEEDED`, and writes every unit's `orchestrator-vision-enrichment.md`. No-marker units still get explicit PASS logs with a local image manifest. Marker units must have structured `### <marker-id>` sections with `status: resolved`, `chapter`, `line`, `marker`, `block_id`, `evidence`, and `patch`; unresolved markers fail Phase 3.0.

Phase 3.1 source indexing is gated by:

```bash
domain-library run library_phase31_source_index --slug "$SLUG"
```

The runner requires Phase 3.0 `PASS`, discovers extraction units, writes one `orchestrator-source-index.md` per unit, embeds hidden `source_index_json`, and validates exact one-to-one coverage: every same-slug chapter block ID appears exactly once in that unit source index, with no extras, duplicates, wrong-slug IDs, or invalid categories.

Phase 3.2 size splitting is gated by:

```bash
domain-library run library_phase32_size_split --slug "$SLUG"
```

The runner requires Phase 3.1 `PASS` and enforces the canonical 2000-line, zero-overlap size policy. If all units are below the threshold, it writes a no-op `PASS`. If any unsplit unit is oversized, it splits into `*-partNN.md`, archives superseded pre-split `team-<unit_id>` directories, rediscovers units, updates `manifest.json`, regenerates current-unit `orchestrator-vision-enrichment.md` and `orchestrator-source-index.md`, writes `raw/papers/$SLUG/size-split-report.json`, writes `_meta/extractions/$SLUG/gates/phase-3.2.json`, and advances state to `READY_FOR_3.3`. Overlap is forbidden because duplicated lines duplicate block IDs.


Then specialist dispatch creates named-lane specialist work. Specialist workers read the source index and source chapter; they do not rebuild source indexes. Phase 3.3 is a agent-runtime step wrapped by deterministic scripts:

```bash
domain-library run library_phase33_dispatch --slug "$SLUG" --prepare
```

Open `_meta/extractions/$SLUG/specialist-dispatch-plan.json`. It validates the shipped prompt contracts and lists one runtime-neutral assignment per configured unit/lane pair, including both expected outputs.

Every generated invocation assignment must include the Phase 3.3 evidence-hygiene contract before dispatch: block embeds use exactly the assignment `Embed target` before `#^blockID`; provenance Relations target chapter block links rather than `[[source]]`, the bare slug, or a unit id; schema JSON block IDs are bare IDs with no leading `^`, brackets, aliases, or paths; and Relations use PAGE_SCHEMA predicates, including `relates_to::` rather than `related_to::`.

Use the current operator's native subagent mechanism for every generated assignment. Write `_meta/extractions/$SLUG/dispatch-result.json` with actual metadata:

```json
{
  "schema_version": 1,
  "slug": "<slug>",
  "tasks": [
    {
      "id": "DefsCh01",
      "runtime_task_id": "<real-runtime-task-id>",
      "job_id": "<real-runtime-job-id>",
      "runtime": "<runtime-name>",
      "model": "<actual-model>"
    }
  ]
}
```

Record dispatch and advance only after every task has real IDs, runtime/model metadata, and both expected files:

```bash
domain-library run library_phase33_dispatch \
  --slug "$SLUG" \
  --record \
  --dispatch-result "_meta/extractions/$SLUG/dispatch-result.json"
```

Prepare-only plans must not be treated as Phase 3.3 `PASS`. Planned model strings are not proof of routing. The recorded report contains deterministic idempotency keys, actual routing metadata, and both markdown and schema JSON draft output paths for each unit/lane so Phase 3.4 can verify outputs and run schema validation.

Phase 3.4 specialist verification is gated by:

```bash
domain-library run library_phase34_verify --slug "$SLUG"
```

The runner requires Phase 3.3 `PASS` and verifies only the recorded recorded unit/lane outputs. Markdown outputs must exist, be non-empty, contain required lane sections, avoid placeholder/slop markers, cite only same-unit same-slug source-index block IDs, and pass evidence-hygiene checks: no `related_to::`, no bare block-evidence predicates without `#^`, no bracketed block IDs, and no malformed extra-bracket embeds. Schema JSON drafts under `_meta/extractions/$SLUG/schema/` must be exactly the files declared by dispatch and must pass `_meta/scripts/schemas/extraction_schema.py`. The runner writes `specialist-verification.json`, `schema-validation-report.json`, `_validation_passed`, and `pipeline-run-manifest.json`, then advances state to `READY_FOR_3.5`. `_validation_passed` is invalid if hand-written or stale; the runner removes stale markers on failure.

Phase 3.4 deliberately does not check `team-<unit_id>-presentation.md`. Presentation assembly and presentation-specific validation happen in Phase 3.5, fixing the old ordering mismatch where the verifier expected a later artifact.

Phase 3.5 team presentation assembly is gated by:

```bash
domain-library run library_phase35_presentations --slug "$SLUG"
```

The runner requires Phase 3.4 `PASS`, assembles every current `team-<unit_id>-presentation.md` from verified named-lane markdown via `team_presentation_assembler.py`, then validates the presentation artifact. Validation requires all assembled sections exactly once, same-unit source-index block citations in every section, at least two block embeds, at least two substantial `Author's Words` quote lines, no placeholder/slop markers, and manifest updates. It writes `presentation-report.json`, `presentation-evidence-balance-audit.json`, and `presentation-evidence-balance-audit.md`; updates `pipeline-run-manifest.json`; writes `gates/phase-3.5.json`; and advances state to `READY_FOR_4`. The evidence-balance audit is advisory: it flags section citation/embed imbalance across Author's Words, definitions, formulas, examples, limitations, relations, and the unit evidence index, but it does not lower the Phase 3.5 gate or authorize unsupported content.

## Phase 4 — Merge and scoring

Prepare Phase 4 with:

```bash
domain-library run library_phase4_merge_score --slug "$SLUG" --prepare
```

The prepare step requires Phase 3.5 `PASS`, the Phase 3.4 schema validation marker/report, and schema JSON drafts under `_meta/extractions/$SLUG/schema/`. It merges and scores schema JSON with `scoring_layer.py`, applies threshold/top-N, filters LaTeX/artifact slugs with `latex_slug_filter.py`, validates all schema JSON block IDs against active chapters with `blockid_validator.py`, writes `_blockid_valid`, and writes `concept-selection-candidates.md/json` plus `concept-selection-rationale-packet.md/json`. The rationale packet is mandatory: every scored concept stays visible with supporting lanes, strongest block IDs, source-section diversity, duplicate/alias risks, and a reason for inclusion or exclusion. The phase gate is `AWAITING_USER_CONFIRMATION`, not `PASS`.

Present `concept-selection-candidates.md` and `concept-selection-rationale-packet.md` to the human reviewer. After the human reviewer selects slugs, write:

```json
{"confirmed_slugs": ["selected-concept-slug"]}
```

to `_meta/extractions/$SLUG/phase4-user-selection.json`, then confirm:

```bash
domain-library run library_phase4_merge_score \
  --slug "$SLUG" \
  --confirm \
  --selection "_meta/extractions/$SLUG/phase4-user-selection.json"
```

Only the confirm step writes Phase 4 `PASS` and advances to `READY_FOR_5`. No concept can be silently discarded: the candidate markdown records clean candidates, all scored concepts, and LaTeX/artifact slugs removed by the filter, while the rationale packet records inclusion/exclusion reasons and evidence signals for every scored concept.

## Phase 5 — Page creation

Run canonical page creation only after Phase 4 confirmation `PASS`:

```bash
domain-library run library_phase5_pages --slug "$SLUG"
```

The runner consumes `master-confirmed.json` to know which concepts the human reviewer approved, but page prose and evidence come from Phase 3.5 team presentations. It refuses existing pages unless `--force` is explicitly provided. Generated concept pages live under `concepts/`, use `yaml_serializer.py` frontmatter ordering, update `index.md` and `log.md`, and must include `## Author's Words`, `## Source-grounded definition`, `## Specific Example`, `## Relations`, `## Evidence index`, at least two block embeds, at least two substantial quote lines, and `extracted_from::` provenance. `derived_from::` is forbidden for initial extraction pages.

The runner writes `_meta/extractions/$SLUG/page-build-report.json`, `_meta/extractions/$SLUG/gates/phase-5.json`, and advances state to `READY_FOR_POST`. Do not use book-specific direct page builders for this phase.

## Post — final audit

The final declaration of completion requires `library_audit.py` exit code 0.
