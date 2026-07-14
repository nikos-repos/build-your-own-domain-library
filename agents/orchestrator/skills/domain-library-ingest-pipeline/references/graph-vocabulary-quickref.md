# Graph Vocabulary Quickref

Use this quickref for Domain Library extraction workers. Read the full `_meta/contracts/VOCABULARY_GUIDE.md` only when changing vocabulary policy.

## Predicate syntax

Use Obsidian-style construction predicates as markdown list items:

```md
- extracted_from::[[raw/papers/<slug>/chapters/<chapter-file>#^<block-id>|^<block-id>]]
  - why this source supports the page claim
  - (target the owning chapter file — never a note named `source`; see PAGE_SCHEMA "Embeds & Evidence Links")
```

## Mandatory provenance rule

- New book-extracted pages use `extracted_from::`.
- Mature synthesis pages may later add `derived_from::`, `abstracted_from::`, `implements::`, or other higher-order predicates.
- Do not use `derived_from::` for initial extraction pages.

## Allowed high-value predicates

| Predicate | Use when |
|---|---|
| `extracted_from::` | direct source block supports a concept/page |
| `defined_by::` | source block gives a definition |
| `formulated_by::` | source block gives equation/formula/model |
| `illustrated_by::` | source block gives example/figure/table/code |
| `warned_by::` | source block gives caveat/limitation/risk |
| `validated_by::` | source reports evidence supporting claim/model |
| `invalidated_by::` | source reports contradiction/failure |
| `contradicts::` | source conflicts with another page/source |
| `implements::` | code/procedure implements model/concept |
| `calibrated_by::` | empirical data calibrates parameter/model |
| `relates_to::` | last resort only; must include annotation |

## Rules

1. Every predicate must be source-grounded or explicitly marked as later synthesis.
2. Avoid single-word vague predicates.
3. Prefer specific predicates over `relates_to::`.
4. Every extracted page needs block embeds, not only YAML metadata.
5. Never invent relationships not named or strongly implied by the source.
