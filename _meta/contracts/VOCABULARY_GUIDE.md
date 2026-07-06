---
created: 2026-04-12
did: "did:repo:53936a6c815841cab48caa0ac46e37364a197e86"
github: "https://gist.github.com/ChristopherA/151aefa6a6bde1ce4fa6b1182656cebe"
purpose: "Agent reference for wikilinks and named edges in plain-markdown knowledge graphs"
copyright: "©2026 by @ChristopherA, licensed under CC-BY 4.0 (https://creativecommons.org/licenses/by/4.0/)"
summary: "How wikilinks and named edge predicates work in a plain-markdown knowledge graph. Covers syntax, YAML vs body predicates, node types (atomic and compound), annotated predicates, vocabulary curation (folksonomy vs ontology), classification predicates (conforms_to:: over is_a::) and predicate conflation, naming sovereignty across collaborating systems, and agent traversal patterns."
---

- conforms_to::[[reference-guide-contract]]
- authored_by::[[christopher-allen]]
- adapted_by::[[niko-bono]]
- in_domain::[[deep-context-architecture]]

# Wikilinks and Predicate Syntax <u>FULL</u> Reference Guide.

A collection of markdown files become a WORKING library through two levers: **wikilinks** connecting files, and **predicates** which label what those connections mean.

A **predicate** is the part of a sentence that describes the action or state of the subject, always containing a **verb** and all associated modifiers, objects, or complements.

These labels cleanly distinguish citation from counterargument. Good labeling requires a defined vocabulary rule set. 

This guide covers those predicates when written inline in markdown.

## Wikilinks: Connections Between Markdown Files

A wikilink references another markdown file with double brackets:

```
[[some-concept-name]]
```

The target is a filename slug without `.md`. When `file-a.md` contains `[[file-b]]`, that creates an edge between two nodes.

Without wikilinks, a collection is a flat set of files. With wikilinks, files connect into traversable chains and clusters. Every file is a **node**, every wikilink creates a web. 

A plain wikilink answers "What is this file about?" It does not describe the *nature* of the connection.

### Wikilinks are bidirectional in practice

If `file-a.md` links to `[[file-b]]`, any tool that indexes the collection can discover:

- **Outgoing links** from `file-a.md` by reading the file
- **Incoming links** to `file-b.md` by searching all files for `[[file-b]]`

Discovering incoming links requires a search across all files:

```bash
rg '\[\[file-b\]\]' --type md
```

### Naming Discipline

Wikilink targets are filenames. Avoid single-word wikilinks. `[[security]]` or `[[design]]` are too bland, collide with multiple meanings, and create noise.

Prefer multi-word descriptive slugs. Specific enough that a second author would never independently generate the same filename.

| Avoid          | Prefer                                                         |
| -------------- | -------------------------------------------------------------- |
| `[[security]]` | `[[self-sovereign-identity]]`                                  |
| `[[design]]`   | `[[pattern-language-design]]`                                  |
| `[[trust]]`    | `[[trust-establishment-protocol]]`                             |
| `[[model]]`    | `[[principal-agent-relationship-in-augmented-knowledge-work]]` |

### Link to a specific section within a file

```
[[file-name#section-heading]]
```

Heading links point to specific sections rather than whole files. Use them for:

- Large files covering multiple concepts. Points to the relevant section such as raw chapter markdown.
- Files where each heading presents a distinct idea.
- Inline citations of specific arguments or definitions

The heading anchor must match the target section. Aimlessly renaming headings breaks section links.

### Ghost Links

A wikilink can point to a file that does not yet exist. Obsidian automatically creates the file when you click on a wikilink with no target. Ghost links can be a planning tool. 

## Predicates: Typed, Directional Relationships

Wikilinks can connect files but do not explain the connection. This is where **predicates** come into play.

```
- predicate_name::[[target-node]]
```

The predicate names the relationship. The double colon (`::`) separates the predicate from the target. The wikilink identifies the destination.

### How this differs from a plain wikilink

| Syntax                                            | Question answered       | Example                                        |
| ------------------------------------------------- | ----------------------- | ---------------------------------------------- |
| `[[elliptic-curve-cryptography]]`                 | "What is this about?"   | This file is about elliptic curve cryptography |
| `derived_from::[[applied-cryptography-handbook]]` | "How does this relate?" | This file was derived from that source         |
| `contradicts::[[centralized-key-management]]`     | "How does this relate?" | This file contradicts that approach            |

### Syntax Details

Predicate blocks are written as items in the **body** of the markdown file. Under the stricter page schema, classification predicates belong immediately after YAML frontmatter and before the H1. Semantic, provenance, structural, lifecycle, and generative predicates belong in the `## Relations` section at the bottom:

```markdown
---
created: 2026-03-05
summary: "A brief description"
---

- conforms_to::[[pattern-form-contract]]
- has_status::[[seed-stage]]
- in_domain::[[deep-context-architecture]]

# File Title

Content begins here...
```

Use a dedicated Relations section for non-classification predicates:

```markdown
## Relations

- relates_to::[[some-concept]]
- derived_from::[[source-document]]
- contradicts::[[opposing-view]]
```

### New Predicate Naming Conventions

**Prefer multi-word predicates with underscores.** Single-word predicates can be too vague.

| Avoid      | Prefer           | Why                                                                                              |
| ---------- | ---------------- | ------------------------------------------------------------------------------------------------ |
| `source::` | `derived_from::` | "Source" could mean origin, format, or repository                                                |
| `type::`   | `conforms_to::`  | "Type" is overloaded; `conforms_to::[[x-form-contract]]` names contract-compliance, not identity |
| `status::` | `has_status::`   | More specific, reads as a sentence                                                               |
| `link::`   | `relates_to::`   | "Link" describes the mechanism, not the relationship                                             |
| `parent::` | `extends_upon::` | "Parent" implies hierarchy; `extends_upon::` describes the relationship                          |

Multi-word predicates read as sentence fragments: "this node `conforms_to` pattern-form-contract," "this node `derived_from` source-document."

### Multiple values for the same predicate

A node can carry multiple lines with the same predicate name:

```markdown
- in_domain::[[decentralized-identity]]
- in_domain::[[self-sovereign-identity]]

- derived_from::[[source-document-a]]
- derived_from::[[source-document-b]]
```

A file with two `in_domain::` lines belongs to two domains. A file with two `derived_from::` lines records two source relationships.

### Predicates used by Your-Domain-[x]-Library

**Classification** (what kind of thing is this?):

- `conforms_to::[[x-form-contract]]` — structural contract this node satisfies. Prefer over `is_a::[[x-form]]`. Created nodes conform to a spec; a node is not identical to the spec.
- `has_status::[[status-name]]` — lifecycle stage (supersedes, folded into, validated by, invalidated by)
- `in_domain::[[domain-name]]` — knowledge area

**Progeny** (where did this come from?):

- `derived_from::[[source-document]]` — concept node was developed from that source
- `extracted_from::[[source-document]]` — pulled directly out of that document and reserved for backlinks to the raw version of a source document.

**Structural** (how does this relate?):

- `implements_this::[[pattern-or-decision]]` — enacts pattern established in existing concept node
- `extends_upon::[[base-concept]]` — builds on that existing concept
- `contradicts::[[opposing-view]]` — in contention with an established view
- `composes_with::[[related-concept]]` — works together with that other concept

**Lifecycle** (what happened over time?):

- `supersedes::[[old-version]]` — replaced that
- `superseded_by::[[new-version]]` — this was replaced by that
- `folded_into::[[new-version]]` — this became that
- `validated_by::[[supporting-evidence]]` — confirmed by that evidence
- `invalidated_by::[[counter-evidence-case]]` — this case broke that assumption

**Pre-Generative** (what does this produce or require?):

- `proposes::[[candidate-hypothesis]]` — this inquiry puts forward that untested hypothesis
- `use_for::[[future-scenario]]` — this scenario imagines consequences of those forces or drivers
- `signaled_by::[[observable-development]]` — this scenario would be confirmed by that observable development

Every predicate on a page MUST be in this vocabulary OR added here first. Synonym predicates forbidden.

### Predicate Placement Under the Page Schema

The page schema form contract uses strict placement rules:

- **Top-of-page classification block:** `conforms_to::`, `has_status::`, and `in_domain::` appear immediately after YAML frontmatter and before the H1.
- **Bottom `## Relations` section:** provenance, structural, lifecycle, and pre-generative predicates appear after the main body.
- **Annotations:** relationship-specific explanation belongs as an indented bullet under the relevant predicate in `## Relations`.
- **YAML frontmatter:** scalar file properties only. Do not place relationship predicates in YAML.

## YAML Frontmatter vs. In-Body Predicates

Markdown files have multiple places for metadata.

**Is the value a fixed scalar, or a connection to a concept that could have its own file?**

- **Scalars** go in YAML frontmatter: dates, summaries, word counts, slugs. Properties of *this* file. They don't point to other Library nodes.
- **Relationships** go as in-body predicates: type declarations, domain membership, structural connections. These point to concepts with their own definitions. Concepts that are or could be separate files.

| Mechanism          | Question answered                  | Example                                    |
| ------------------ | ---------------------------------- | ------------------------------------------ |
| **YAML field**     | "What are this file's properties?" | `created: 2026-03-05`, `summary: "..."`    |
| **Wikilink**       | "What is this about?"              | `[[elliptic-curve-cryptography]]` in prose |
| **Body predicate** | "How does this relate?"            | `derived_from::[[source-document]]`        |

### Example Decision Ladder

- `created: 2026-03-05` — a date. Dates don't have files. **YAML.**
- `conforms_to::[[pattern-form-contract]]` — "Pattern Form Contract" has its own file with a definition. **Body predicate.**
- `summary: "A brief description"` — text property of this file. **YAML.**
- `in_domain::[[deep-context-architecture]]` — has its own file. **Body predicate.**
- `publication_year: 2008` — scalar number. **YAML.**
- `derived_from::[[concept-name]]` — relational property. **Body predicate.**

### Predicates belong in the body, not frontmatter

Putting relationships in YAML frontmatter hides them from the obsidian graph. YAML is for machines that parse structured metadata; body predicates are for agents and humans who read files and follow connections. A predicate in the body is visible content.

### Growing Your Own Predicate Vocabulary

Predicates on their own are freeform strings. Nothing enforces a controlled vocabulary. This creates failure points, how much structure should the vocabulary have?

### Vocabulary Curation Loop

Start with a small core vocabulary. Included with this repo is a strong base vocabulary. Let it grow through use. You should monitor periodically. Curation requires ongoing work:

1. **Awareness** — list what predicates exist and what each means
2. **Review** — audit for drift: redundant predicates, ambiguous usage, meaning shift
3. **Consolidation** — merge redundant predicates; update existing uses
4. **Clarification** — tighten ambiguous definitions or split into more specific predicates
5. **Enforcement** — reject undeclared predicates at build time

Choosing "use existing" vs. "invent new"

When you need to express a relationship and are unsure which predicate to use:

1. **Check the existing vocabulary.** Search the collection: `rg -o '^- [a-z_]+::' --type md | sort -u`. Use what exists before inventing.
2. **Check if a more specific predicate fits.**  If the predicate states `extracted_from::` but the parent-child relationship is different, use `derived_from::`. Derived from is used in created concept pages while extracted from is for backlinking the raw file in the structured markdown pages. 
3. **If nothing fits, invent deliberately.** Choose a multi-word name that can read as a sentence fragment. Document the new predicate.
4. **Do not invent synonyms.** If `derived_from::` exists, do not create `sourced_from::` for the same meaning. Synonym predicates are the primary mechanism of vocabulary drift.

### Single-word predicates can fail

Single-word predicates collide with themselves and poison precedent.

- **Collision**: `type::` could mean form type, content type, media type, or classification type
- **Precedent poisoning**: Once a vague predicate is allowed to exist, AI Agent Library Workers will treat it as precedent. EX: "this Library page uses `source::`, so I should too." One vague predicate becomes a working template for hundreds

Multi-word predicates with underscores (`derived_from`, `extracted_from`, `has_status`) are self-documenting.

### The name itself matters

Choosing `conforms_to::` over `is_a::` is not cosmetic. It is a claim about who names relationships between nodes and what a name does.

**Use `conforms_to::[[x-form-contract]]` in place of `is_a::[[x-form]]`.** The predicate is longer but names what is actually happening. The target's `form-contract` suffix signals that the form is a specification, not a class of thing.

The `relates_to::` trap: `relates_to::` is the most over-used predicate in any personal knowledge graph. Agents default to it reflexively.

Before writing `relates_to::`, ask: "Can I name the *kind* of relationship?" If a file was derived from a source, use `derived_from::`. If it extends another concept, use `extends_upon::`. If it contradicts something, use `contradicts::`. 

In a library with hundreds of nodes, a query for "everything that relates to X" returns noise. A query for "everything derived from X" returns signal.

## Notes, Nodes, and Compound Nodes

### From note to node

Any markdown file is a **note**. It becomes a **node** when it participates in the Library through predicate labels. 

### Form contracts

A **form contract** is a spec sheet for generated pages with required sections, expected predicates, and body structure conventions.

A node declares which contract it meets with a classification predicate. When developing your Library, reading the form-contract definitions tells you what to expect from every node made to satisfy them. 

### Compound nodes

Not every concept can reliably maintain readability if stuffed in a single file. A **compound node** uses a folder:

```
some-concept/
├── some-concept.md          ← lead file
├── analysis.md              ← sibling file
├── renditions/
│   └── source-article.md    ← format-transformed copy of external source
└── archives/
    └── original-slides.pdf  ← preserved binary original
```

Compound nodes create an isolated zone in the Library dedicated to the concept. 

The **lead file** shares the folder's name and serves as the primary access point. When a wikilink targets `[[some-concept]]`, the lead file is where you arrive. Sibling files carry related analysis that would make the lead file unwieldy. 

Use compound nodes when beginning new experiments with your desired topics. 

## Library Traversal for Queried Agents

### Progressive disclosure via predicates

When an agent working in the Library encounters a new file, predicates tell it what kind of file this is and how it connects *before* reading the body:

1. **Read the classification predicates** (`conforms_to::`, `in_domain::`) — contract, knowledge area. You now know whether this is a pattern, citation, decision, or something else without reading a paragraph.
2. **Scan the semantic predicates** — `derived_from::`, `extends_upon::`, `contradicts::` tell you relationships. Combined with annotations, decide which edges are worth following.
3. **Read the body** — only after predicates have oriented you. For large files, predicates may tell you that following a different path is more productive than reading the file in full.

This is **predicate-first reading**: the opposite of normal prose reading. It lets an agent navigate efficiently, spending reading budget on files that matter most.

### Incoming edge discovery

To find everything that points *to* a specific node:

```bash
# Find all files that link to "target-node" in any way
rg '\[\[target-node\]\]' --type md

# Find all files that link to "target-node" via a specific predicate
rg 'derived_from::\[\[target-node\]\]' --type md
```

## Practical Operations

### Maintenance recipes

**Find all files using a specific predicate:**

```bash
rg 'derived_from::' --type md
```

**Find all files linking to a specific target:**

```bash
rg '\[\[target-node\]\]' --type md
```

**Rename a predicate across all files:**

```bash
rg -l 'old_predicate::' --type md | xargs sed -i '' 's/old_predicate::/new_predicate::/g'
```

**Audit predicate vocabulary (frequency count):**

```bash
rg -o '^- [a-z_]+::' --type md | sort | uniq -c | sort -rn
```

**Discover ghost links (referenced but nonexistent files):**
Extract all `[[targets]]` from predicate lines, compare against existing filenames.

**To find everything that points _to_ a specific node:**

```bash
# Find all files that link to "target-node" in any way
rg '\[\[target-node\]\]' --type md 
# Find all files that link to "target-node" via a specific predicate
rg 'derived_from::\[\[target-node\]\]' --type md
```

## Summary

The core principles:

- Single-word wikilinks are forbidden; they are far too broad to be useful.
- Avoid single-word predicates. They can collide & poison precedent.
- Predicates go in file bodies, not YAML frontmatter.
- YAML frontmatter is for scalars like dates or summaries. Body predicates are for relationships.
- Annotate predicates when the relationship needs context! Annotations enable better progressive disclosure.
- Prefer specific predicates over defaults. Specificity makes the Library queryable.
- Vocabulary requires curation, not just enforcement.
- Adhere to the loop when developing new predicate syntax.
- Read predicates first, body second. For both humans and agents this makes moving through pages lightweight. Classification and relationship predicates can quickly orient you to a page before the actual context does. 
- The Library exists as plain text, a text editor and `rg` are sufficient tools.

## Notice

This vocabulary guide was adapted by Niko Bono for use with a personal library-building system. It is inspired by the work of Christopher Allen, including his public writing on plain-markdown knowledge graphs, wikilinks, and named edges.


