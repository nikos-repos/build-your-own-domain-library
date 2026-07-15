# Deterministic indexing contract

Phase 3.1 is implemented by `_meta/scripts/library_phase31_source_index.py`.
This reference explains its current contract; the runner remains the source of
truth.

Run it only when `python3 library.py next --slug "$SLUG"` reports
`READY_FOR_3.1`:

```bash
domain-library run library_phase31_source_index --slug "$SLUG"
```

## Inputs and outputs

- Input: current extraction units under `raw/papers/$SLUG/chapters/`, with
  same-slug block anchors and a Phase 3.0 vision log for each unit.
- Output: one
  `_meta/extractions/$SLUG/team-<unit-id>/orchestrator-source-index.md` per
  current unit, plus `raw/papers/$SLUG/source-index-report.json` and the Phase
  3.1 gate.
- The Markdown index includes a `source_index_json` comment consumed by later
  phases. Do not edit generated indexes by hand.

The gate passes only when each current chapter block appears exactly once,
every block ID belongs to the current slug and chapter, and every category is
one of the six names below.

## Classification order

`classify()` assigns one category in this priority order:

1. `Formulas`
2. code/data routed to `Examples / Figures`
3. `Definitions`
4. `Warnings / Caveats`
5. `Historical / Empirical References`
6. keyword/numeric `Examples / Figures`
7. restrictive `Transitional / Structural`
8. a late-binding pass for substantive text of at least 12 words

### Signals currently implemented

| Category | Main signals |
| --- | --- |
| Formulas | LaTeX commands, `$$`, escaped display delimiters, or inline `$...$`. Raw brackets are intentionally excluded so citations and wikilinks are not math. |
| Examples / Figures | Code fences, common Python/REPL forms, assignments, numeric/data rows, numbered figure/table/algorithm/listing/example captions, example keywords, or sufficiently long numeric prose. |
| Definitions | Capitalized `Term: ...` entries, explicit definition phrases, or sufficiently long definition keywords. |
| Warnings / Caveats | Caution, limitation, instability, risk, boundary, and advice phrases in blocks of at least five words. |
| Historical / Empirical References | Generic citation/research phrases. The public default intentionally contains no domain-specific surname list. |
| Transitional / Structural | Blocks of at most three words, Markdown headings/rules, explicit transition phrases, or content still unmatched after late binding. |

The exact patterns and word thresholds live beside `classify()` in
`library_phase31_source_index.py`. Change them there, then update this page and
the table-driven classifier regression in
`_meta/scripts/library_pipeline_test_suite.py` in the same commit.

## Verification

```bash
domain-library run library_pipeline_test_suite
python3 library.py next --slug "$SLUG"
```

For a real run, inspect `source-index-report.json`: `status` must be `PASS`,
`total_block_ids` must equal `unique_block_ids`, and each unit must have an
empty `failures` list. Classification quality can be tuned later; coverage and
identity are hard gates.
