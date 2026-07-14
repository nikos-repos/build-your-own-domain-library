# Graph Vocabulary Quickref

Use this quickref for Library extraction workers. It summarizes the `_meta/contracts/PAGE_SCHEMA.md` and `_meta/contracts/VOCABULARY_GUIDE.md` requirements for worker outputs.

Extraction workers produce intermediate extraction artifacts, not final concept pages. They must preserve source-grounded evidence and use only declared vocabulary when proposing candidate relations. The compiler agent is responsible for producing final PAGE_SCHEMA-compliant concept pages.

## Naming rules

- Use lowercase, hyphenated slugs for filenames and wikilink targets.
- Prefer multi-word slugs, usually 2–7 words.
- Single-word filenames and wikilinks are forbidden unless explicitly assigned by the orchestrator.
- External wiki references use `↗` after the closing brackets:
  - `[[concept-that-lives-elsewhere]]↗`

## Predicate syntax

Predicates are typed, directional relationships written as markdown list items:

```md
- predicate_name::[[target-slug]]
  - Optional annotation explaining why the relationship exists.
```

Predicates must be lowercase, underscored, and declared in the PAGE_SCHEMA / VOCABULARY_GUIDE vocabulary before use.

## Predicate placement

Final Library pages follow stricter placement than generic markdown notes:

1. YAML frontmatter comes first.
2. Classification predicates come immediately after frontmatter and before the H1.
3. Main prose follows the H1.
4. Provenance, structural, lifecycle, and pre-generative predicates go in the bottom `## Relations` section.

Extraction workers normally do **not** create final concept pages. If a worker is asked to propose candidate relations, place them under a clearly marked worker section such as `## Candidate Relations`, not a final graph-ingestion `## Relations` section unless explicitly assigned.

## Classification predicates

These belong only in the top-of-page classification block of final Library pages:

| Predicate       | Use when                                            |
| --------------- | --------------------------------------------------- |
| `conforms_to::` | Declaring the form contract a final page satisfies. |
| `has_status::`  | Declaring lifecycle status or stage.                |
| `in_domain::`   | Declaring the knowledge domain.                     |

Workers should not add these to intermediate extraction drafts unless the assignment explicitly asks them to create a PAGE_SCHEMA-compliant page.

## Worker-safe provenance guidance

Use source-grounded provenance carefully. For first-pass book extraction drafts, prefer `extracted_from::` for direct block evidence.

```md
- extracted_from::[[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>|^<block-id>]]
  - Direct source block supporting the extracted definition, formula, claim, example, warning, or candidate concept.
```

Embed the same source block near the relevant quote or claim when the assignment requires block embeds:

```md
> ![[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>]]
```

## Declared predicate vocabulary

Only these predicates are currently declared for Library pages.

### Progeny

| Predicate          | Use when                                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------------------- |
| `derived_from::`   | A concept page was developed from another source or page. Usually compiler/synthesis-stage.          |
| `extracted_from::` | A claim, quote, candidate concept, or extraction is pulled directly from a source document or block. |

### Structural

| Predicate           | Use when                                                                   |
| ------------------- | -------------------------------------------------------------------------- |
| `implements_this::` | A code, procedure, or practice enacts an established pattern or decision.  |
| `extends_upon::`    | A concept builds on an existing concept.                                   |
| `contradicts::`     | A claim or page conflicts with another source-backed claim, page, or view. |
| `composes_with::`   | Two concepts work together as parts of a larger mechanism or framework.    |

### Lifecycle

| Predicate          | Use when                                                                           |
| ------------------ | ---------------------------------------------------------------------------------- |
| `supersedes::`     | A newer page or claim replaces an older one.                                       |
| `superseded_by::`  | An older page or claim has been replaced by a newer one.                           |
| `folded_into::`    | A page or claim has been merged into another page.                                 |
| `validated_by::`   | Evidence supports or confirms a claim, model, or assumption.                       |
| `invalidated_by::` | Evidence breaks, falsifies, or seriously undermines a claim, model, or assumption. |

### Pre-generative

| Predicate       | Use when                                                         |
| --------------- | ---------------------------------------------------------------- |
| `proposes::`    | A source, inquiry, or draft puts forward a candidate hypothesis. |
| `use_for::`     | A scenario or concept is intended for a future use case.         |
| `signaled_by::` | A scenario would be confirmed by an observable development.      |

## Evidence-link rules

Every block embed and block link must resolve in Obsidian. The target is the vault-absolute path of the chapter file that owns the block, without the `.md` extension.

```md
> ![[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>]]
- extracted_from::[[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>|^<block-id>]]
```

Rules:

- Never target `source`, the bare book slug, a unit id such as `ch08` or `ch10-part01`, or a partial path.
- Copy block IDs exactly from the chapter file or source index.
- Do not surround block IDs with square brackets.
- JSON `block_id` and `block_ids` values must be bare IDs with no leading `^`, aliases, paths, embeds, or brackets.
- Non-embed links in candidate relations may use a short alias for readability.
- Actual embeds need no alias.
- The block anchor must exist in the targeted chapter file.

## Forbidden predicates

Do not use undeclared predicates, including:

- `abstracted_from::`
- `calibrated_by::`
- `defined_by::`
- `formulated_by::`
- `illustrated_by::`
- `implements::`
- `related_to::`
- `relates_to::`
- `warned_by::`

If no declared predicate fits, do not invent a synonym. Record the uncertainty in prose for the compiler agent.

## Worker rules

1. Preserve source-grounded evidence.
2. Use `extracted_from::` for direct source-block provenance.
3. Use only declared PAGE_SCHEMA / VOCABULARY_GUIDE predicates when proposing candidate relations.
4. Do not use final page classification predicates unless explicitly assigned.
5. Do not create final `## Relations` sections unless explicitly assigned.
6. Never invent relationships not named or strongly implied by the source.
7. Never present paraphrase as quotation.
8. Every substantive extraction claim should cite same-slug block evidence.
9. When content is absent from the assigned source range, say so explicitly instead of fabricating replacement content.
