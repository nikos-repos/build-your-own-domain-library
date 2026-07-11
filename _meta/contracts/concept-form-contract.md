---
title: concept-form-contract
created: 2026-04-23
updated: 2026-04-23
confidence: 1.0
tier: procedural
quality: 0.9
scope: shared
author: orchestrator
---

- conforms_to::[[form-contract]]
- has_status::[[evergreen]]
- in_domain::[[meta]]

# Concept Form Contract

Specification for concept/topic pages (strategies, methods, models, metrics).

## Required Classification Predicates

- `conforms_to::[[concept-form-contract]]`
- `has_status::[[seed|growing|evergreen]]`
- `in_domain::[[<domain-slug>]]`

## Required Relations

- `extracted_from::[[<source-slug>]]` (at creation)
  - Must include block-level annotations: `Ch. N, block ^id — <what>`
- `informed_by::[[<related-concept>]]` (as needed)
  - Annotation required explaining the relationship per the author.

## Body Structure

1. **H1 title** — concept name
2. **Abstract callout** with a block embed of the owning chapter file — `![[raw/papers/<slug>/chapters/<chapter-file>#^<block-id>]]` (PAGE_SCHEMA "Embeds & Evidence Links"; never target `source`) — author's exact definition
3. **`## Author's Words`** — verbatim quotes of 2+ sentences
4. **`## Author's Formulation`** — exact formulas with author's variable names
5. **`## Specific Example`** — a concrete, source-grounded illustration with block evidence
6. **`## Implementation Details`** — code, pseudocode, algorithm steps (if author provides)
7. **`## Figures and Diagrams`** — detailed description of author's visuals
8. **`## Author's Warnings`** — ALL specific caveats (not one; all of them)
9. **`## Limitations and Counter-Arguments`** — author's own limitations and criticisms
10. **`## Historical / Empirical Context`** — background, studies, real-world references
11. **`## Relations`** — provenance and structural predicates with annotations

## Anti-Fluff Rules

- No sentence that could be written without reading the source.
- No filler transitions ("It is important to note that...").
- No unattributed hedging ("Some people believe...").
- Minimum 80 lines total (frontmatter + body + Relations).

# 
