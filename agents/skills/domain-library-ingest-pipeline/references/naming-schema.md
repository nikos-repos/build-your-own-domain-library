# Naming Schema

## Owners

| Old role | New owner/lane | New output |
|---|---|---|
| Agent 0 Vision | Orchestrator | `orchestrator-vision-enrichment.md` |
| Agent 1 Source Index | Orchestrator | `orchestrator-source-index.md` |
| Agent 2 Definitions | `defs` | `domain-definitions.md` |
| Agent 3 Formulas | `math` | `domain-math.md` |
| Agent 4 Examples | `examples` | `domain-examples.md` |
| Agent 5 Warnings | `warnings` | `domain-warnings.md` |
| Agent 6 Empirical Context | `context` | `domain-empirical-context.md` |

## Extraction units

`unit_id` is the routing and output namespace.

| Filename | Unit ID | Output directory |
|---|---|---|
| `ch-01-introduction.md` | `ch01` | `_meta/extractions/<slug>/team-ch01/` |
| `ch-08-risk-part2.md` | `ch08-part02` | `_meta/extractions/<slug>/team-ch08-part02/` |
| `part-001.md` | `ch00-part001` | `_meta/extractions/<slug>/team-ch00-part001/` |

Block IDs remain compatible: `^<slug>-chNN-####`. Bare fallback chunks use `ch00` with a global counter across all fallback files.

Phase 3.2 size splitting emits `*-partNN.md` files from previously unsplit `chNN` units only. Nested splits of already-parted files are forbidden because `unit_id` has a single part namespace and recursive parts would collide.

## Named lane worker profile profiles

| Lane | Global agent profile |
|---|---|
| `defs` | `_meta/agents/defs.md` |
| `math` | `_meta/agents/math.md` |
| `examples` | `_meta/agents/examples.md` |
| `warnings` | `_meta/agents/warnings.md` |
| `context` | `_meta/agents/context.md` |

Lane worker profiles under `_meta/agents/<lane>.md` (or `AGENT_PROFILE_DIR`) are the only Phase 3.3 sources of truth. Task IDs remain deterministic CamelCase handles derived from `<lane><unit_id>`, while durable idempotency keys remain `<slug>:<unit_id>:<lane>`.
