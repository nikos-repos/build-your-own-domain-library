---
name: domain-library-run-and-operate
description: |
  Running the Domain-Library ingest pipeline day to day: the unified state
  runner (the anti-drift tool), command anatomy, artifact conventions, what
  lands where, and operating discipline. The operating contract itself lives
  in the domain-library-ingest-pipeline skill; this skill is how you drive it
  without drifting.
related_skills:
  - domain-library-ingest-pipeline
---

# Domain-Library Run and Operate

## The unified state runner — use it every time

Agent drift : running phases out of order, re-running finished work,
treating prepare artifacts as results, inventing commands have caused most major
failures in this project's history. The state runner exists so nobody ever
guesses the next command:

```bash
# What do I do next for this book?
python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --slug <slug>

# Status of every ingest in the library:
python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --all

# Machine-readable (for agents):
python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --slug <slug> --json
```

It reads `_meta/extractions/<slug>/pipeline-state.json` plus the gate files,
cross-checks them, and prints exactly one of: the canonical next command; the
human-gate instructions; a BLOCKED explanation; or a **DRIFT** report (exit 2)
when recorded state and on-disk gates disagree. **Exit 2 means stop and
reconcile — trust the gate files, and fix via the debugging playbook, never
by editing state.**

Operating rule for agents: *run the state runner before and after every
phase.* If your intended command differs from its NEXT line, you are drifting. Stop.

## Command anatomy

Every phase runner follows the same shape:

```bash
python3 _meta/scripts/library_phase<N>_<name>.py --slug "$SLUG" [--wiki "$WIKI"] [phase-specific flags]
```

- Run from the library root; `--wiki` defaults to the repo root derived from
  the script's location.
- Exit 0 = gate PASS written. Exit 2 = gate FAIL written with the reason
  inside. Non-gate crash = bug; report it.
- Full per-phase table with gates: `agents/orchestrator/skills/domain-library-ingest-pipeline/SKILL.md`
  (the operating contract — canonical). Reference detail:
  `references/runbook-full.md`, `references/phase-gates.md`.

The complete phase order: `1 → 1.5 → 2.1 → 2.2 → 2.3 → 2.4 → 3.0 → 3.1 →
3.2 → 3.3 (prepare → dispatch → record) → 3.4 → 3.5 → 4 (prepare → HUMAN
CONFIRM → confirm) → 5 → post (grounding QA + audit)`. Phases 1/1.5 and
2.1/2.2 share a runner each.

## Two special phases

- **3.3 is three steps**, and only the middle one involves agents:
  `--prepare` (writes the validated dispatch plan) → launch specialist agents
  per `references/specialist-dispatch-protocol.md` using the current runtime's
  native subagent mechanism → `--record --dispatch-result …` (verifies real
  runtime/model/task/job IDs and both outputs, then writes the gate). Prepare output is not a PASS.
- **4 contains the human gate.** After `--prepare`, state is
  `AWAITING_USER_CONFIRMATION`: present `concept-selection-candidates.md` and
  the rationale packet to the library owner, write their choices to
  `phase4-user-selection.json` (`{"confirmed_slugs": [...]}`), then
  `--confirm --selection …`. No automation may cross this gate.

## What lands where

| Artifact                                                      | Path                                                            |
| ------------------------------------------------------------- | --------------------------------------------------------------- |
| OCR output, combined JSON, images                             | `raw/papers/<slug>/glmocr_output/`                              |
| Reconstructed book                                            | `raw/papers/<slug>/book_fidelity.md`                            |
| Chapters with block anchors                                   | `raw/papers/<slug>/chapters/*.md` (+ `chapters/images/`)        |
| Book-level reports (blocks, images, source index, size split) | `raw/papers/<slug>/*.json`                                      |
| Pipeline state                                                | `_meta/extractions/<slug>/pipeline-state.json`                  |
| Gates                                                         | `_meta/extractions/<slug>/gates/phase-*.json`                   |
| Per-unit orchestrator + specialist outputs                    | `_meta/extractions/<slug>/team-<unit_id>/`                      |
| Schema JSON drafts                                            | `_meta/extractions/<slug>/schema/`                              |
| Scoring/selection artifacts                                   | `_meta/extractions/<slug>/master-*.json`, `concept-selection-*` |
| **Published pages (the product)**                             | `concepts/*.md`                                                 |
| Catalog + action log                                          | `index.md`, `log.md`                                            |
| Audit reports                                                 | `_meta/reports/`                                                |

## Operating discipline

- **Idempotent by design, guarded by latches.** Reruns are safe up to the
  overwrite latches; `--force` is an owner decision, logged.
- **Never run two phases for the same slug concurrently.** State is a single
  JSON file; the design is strictly sequential per slug. Different slugs may
  run in parallel.
- **log.md and index.md are maintained by the machinery** (`append_log` on
  every state write; Phase 5 updates the index; `rebuild_index.py`
  regenerates it in full). Don't hand-edit; if the index looks stale, rerun
  `python3 _meta/scripts/rebuild_index.py`.
- **Disk hygiene after a successful ingest:**
  `python3 _meta/scripts/prune_raw.py --slug <slug> --apply` deletes
  recreatable PDF chunks once fidelity has PASSed (dry-run without
  `--apply`).
- **Completion claim** requires the post-phase: grounding QA + audit exit 0
  (with `--ack` for hand-verified manual checks). "Pages exist" is not done.

# 
