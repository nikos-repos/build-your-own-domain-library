# Domain Library Page Schema.

## Your Domain.

The domain summary is configured in `_meta/config/domain.json` under `domain_summary`.

EX:

*"Quantitative finance: statistical modeling, live trading systems, market microstructure, risk management, and agent-based research infrastructure."* (my actual use-case).

## Naming Conventions.

- Filenames: lowercase, hyphenated, no space.
  - `scientific-method-overview.md`, not `Scientific Method Overview.md`.
- Multi-word, 2-7 words.
  - Single-word filenames forbidden.
- External wiki refs are marked with `↗` trailing the closing brackets:
  - `[[concept-that-lives-elsewhere]]↗`.

## Page Structure.

A Library page follows this structure:

1. **YAML frontmatter**
2. **Classification predicate block** — right after the frontmatter, before the H1.
3. **H1 title + prose body** with inline `[[wikilinks]]` for "what this is about" connections.
4. **`## Relations` section at the bottom** — semantic, provenance, structural, lifecycle, and generative predicates with optional indented annotations.
- Minimum 2 outbound connections per page.
- On update: bump `updated` YAML.
- New page is added to `index.md` under the correct section.
- Each action is appended to `log.md`.

## Frontmatter (YAML scalars).

```yaml
---
title: page-slug
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: 0.0–1.0
contested: true
quality: 0.0–1.0
quality_notes: "single source; low cross-ref"
scope: private | shared
author: agent-id | human-id
---
```

## Body Structure.

After the frontmatter closing, `---`, before H1:

```markdown
- conforms_to::[[<form-contract-slug>]]
- has_status::[[<status-stage-slug>]]
- in_domain::[[<domain-slug>]]
```

At the bottom of pages, after main content:

```markdown
## Relations

- derived_from::[[<source-page-slug>]]
  - Annotation explaining why this source matters for this node.
- contradicts::[[<opposing-page-slug>]]
  - Annotation: what specifically contradicts.
```

## raw/ Frontmatter.

(Post OCR phase)

```yaml
---
source_url: https://example.com/article
ingested: YYYY-MM-DD
sha256: <hex digest of body>
sensitive_filtered: true
scope: private | shared
--- 
```

## Predicate Vocabulary.

Predicates are **underscored**, lowercase, and preferred to be multi-word. 

[*See VOCABULARY_GUIDE.md for full guide*]

**Classification (top-of-page block, every node):**

* `conforms_to::[[x-form-contract]]`
* `has_status::[[x-stage]]`
* `in_domain::[[x]]`

**Additional predicate types:**

**Progeny:** `derived_from::`, `extracted_from::`

**Structural:** `implements_this::`, `extends_upon::`, `contradicts::`, `composes_with::`,

**Lifecycle:** `supersedes::`, `superseded_by::`, `folded_into::`, `validated_by::`, `invalidated_by::`

**Pre-Generative:** `proposes::`, `use_for::`, `signaled_by::`

**Rules:** Every predicate on a page <u>MUST</u> be in this vocabulary OR *added here* first. Synonym predicates forbidden.

## Confidence Score Policy.

- New claim from single source → `confidence: 0.5`.
- Each additional confirming source → `+0.125`, caps @ 0.95.
- Explicit contradiction new source → halve confidence, set `contested: true` and add `- contradicts::[[<other-page>]]`.
- Time-based decay/reinforcement: **THIS FEATURE IS ON THE WAY**  *[Will be introduced here
  when a maintenance job is built.]*

`quality:` is computed at build time from section completeness, author-quote count, evidence-block count. Page creation is gated for real signals. `quality_notes` records the inputs.

## Superseded Page Policy.

When a new claim contradicts an existing one:

1. NEVER overwrite the old page.
2. Create a new page with the updated claim.
3. On the new page, add `- supersedes::[[<old-page-slug>]]` to Relations.
4. On the old page, add `- superseded_by::[[<new-page-slug>]]` to Relations.
5. Add `> [!warning] Superseded by [[new-page]] on YYYY-MM-DD` callout at top of old page before H1.

## Embeddings & Evidence Links.

Every block embed and block link must resolve in Obsidian. The target is the **vault-absolute path of the chapter file that owns the block**,
without the `.md` extension:

```markdown
> ![[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>]]
- extracted_from::[[raw/papers/<book-slug>/chapters/<chapter-file>#^<block-id>|^<chNN-NNNN>]]
```

Rules enforced by `wiki_integrity.py`

- Never target `source`, the bare book slug, a unit id (`ch08`, `ch10-part01`),
  or a partial path. None of these resolve.
- Block IDs are copied exactly, with no surrounding square brackets.
- Non-embed links in Relations should carry a short alias (`|^ch10-0400`)
  for human readability. Actual embeds need no alias.
- The block anchor must exist in the targeted chapter file. Pre-split
  `.orig.md` copies live in `archive/`, never in `chapters/`.

## Form Contracts.

Pages are concepts and conform to `_meta/contracts/concept-form-contract.md`. 

## Privacy Policy

- Default scope `private`. Promote to `shared` only upon confirmation.
- Strip API keys, tokens, and PII before writing to `raw/`. Mark `sensitive_filtered: true`.
- Do not release private raw files.
- Do not release proprietary source dumps.
- Do not include local paths.
- Do not include unpublished client or work material.
