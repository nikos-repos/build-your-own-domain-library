# Naming Schema

## Owners

| owner/lane   | output                              |
| ------------ | ----------------------------------- |
| Orchestrator | `orchestrator-vision-enrichment.md` |
| Orchestrator | `orchestrator-source-index.md`      |
| `defs`       | `domain-definitions.md`             |
| `math`       | `domain-math.md`                    |
| `examples`   | `domain-examples.md`                |
| `warnings`   | `domain-warnings.md`                |
| `context`    | `domain-empirical-context.md`       |

## Extraction units

`unit_id` is the routing and output namespace.

| Filename                | Unit ID        | Output directory                              |
| ----------------------- | -------------- | --------------------------------------------- |
| `ch-01-introduction.md` | `ch01`         | `_meta/extractions/<slug>/team-ch01/`         |
| `ch-08-risk-part2.md`   | `ch08-part02`  | `_meta/extractions/<slug>/team-ch08-part02/`  |
| `part-001.md`           | `ch00-part001` | `_meta/extractions/<slug>/team-ch00-part001/` |

Block IDs remain compatible: `^<slug>-chNN-####`. Bare fallback chunks use `ch00` with a global counter across all fallback files.

Phase 3.2 size splitting emits `*-partNN.md` files from previously unsplit `chNN` units only. Nested splits of already-parted files are forbidden because `unit_id` has a single part namespace and recursive parts would collide.

## Named lane worker profile profiles

| Lane       | Global agent profile       |
| ---------- | -------------------------- |
| `defs`     | `agents/library-workers/domain-defs/defs.md`     |
| `math`     | `agents/library-workers/domain-math/math.md`     |
| `examples` | `agents/library-workers/domain-examples/examples.md` |
| `warnings` | `agents/library-workers/domain-warnings/warnings.md` |
| `context`  | `agents/library-workers/domain-context/context.md`  |

Lane worker profiles under `agents/library-workers/domain-<lane>/<lane>.md` (or `AGENT_PROFILE_DIR`) are the only Phase 3.3 sources of truth. Task IDs remain deterministic CamelCase handles derived from `<lane><unit_id>`, while durable idempotency keys remain `<slug>:<unit_id>:<lane>`.
