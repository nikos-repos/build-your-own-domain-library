# Build Your Own Domain Library

[![CI](https://github.com/nikos-repos/build-your-own-domain-library/actions/workflows/ci.yml/badge.svg)](https://github.com/nikos-repos/build-your-own-domain-library/actions/workflows/ci.yml)

An academic book ingestion and extraction pipeline for building a markdown knowledge base from PDFs. Inspired by the LLM Wiki pattern proposed by Andrej Karpathy, but revamped in a way that **actually works.** This gated pipeline turns a raw source document (such as 900+ page books, and academic research articles) into **source-grounded, rich concept pages**.

Concept pages are markdown Library pages where every single claim you can see is backed by a click-through embed of the exact source passage.

For me, this system makes tackling advanced subjects feel like a treasure hunt:

Pick a concept that sounds cool → Read the detailed concept page → Navigate back to the full chapter for anything you don't understand → Repeat.

## What the pipeline does

This customizable workflow runs OCR, reconstructs raw source material into structured markdown, splits chapters, assigns stable block IDs to each text chunk, classifies text blocks, dispatches specialist extraction workers, verifies gathered evidence, scores candidate concepts, waits for human review, and writes final schema-compliant pages per [`_meta/contracts/PAGE_SCHEMA.md`](_meta/contracts/PAGE_SCHEMA.md).

## Who this is for

* Researchers, students, independent scholars, or users new to AI-assisted tools desiring a useful system that isn't just hype.

* Anybody who was disappointed when their "LLM-Wiki" or "AI second-brain" project never actually functioned for reproducible evidence-linked knowledge extraction.

## Quickstart

```bash
git clone https://github.com/nikos-repos/build-your-own-domain-library.git
cd build-your-own-domain-library
python3 -m venv .venv  # Python 3.12+
. .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
cp .env.example .env
# Edit .env and replace ZHIPU_API_KEY=replace_me with your key.
domain-library doctor --full
```

### Configuration and secrets

Customize `_meta/config/domain.json` for your field. Its `lanes` array defines the specialist prompt contracts and expected outputs. The specialist worker prompt contracts live under `agents/library-workers/` (one folder per lane, referenced by `domain.json`).

The only repository-owned secret is `ZHIPU_API_KEY` in the root `.env`. The OCR client also reads `GLM_OCR_TIMEOUT` there. Agent runtimes choose their own model and authentication; the repository records the actual runtime, model, task ID, and job ID after dispatch.

## Output and proof

Published pages are written under `concepts/`. A license-attributed mini example result is available in [`examples/demo-library`](examples/demo-library/README.md).

The canonical phase workflow is the [ingest skill](agents/orchestrator/skills/domain-library-ingest-pipeline/SKILL.md). Page requirements are in [`_meta/contracts/PAGE_SCHEMA.md`](_meta/contracts/PAGE_SCHEMA.md), and security guidance is in [`SECURITY.md`](SECURITY.md).

Setup is intended to take only a few minutes after Python and an OCR key are available. Full ingestion time and OCR cost will scale with document size.

## Cost and token ledger

Each OCR API response and dispatch task that reports tokens appends an immutable
JSON line to `_meta/extractions/<slug>/cost-ledger.jsonl`. OCR responses without
token metadata record their page count as a clearly labeled proxy. The final
audit report includes aggregate input/output tokens and per-phase totals; USD
conversion is intentionally not performed.

## Safe reruns

To re-run a phase without deleting source or generated artifacts:

```bash
domain-library rerun --slug "$SLUG" --from 3.3 --yes
domain-library next --slug "$SLUG"
```

`rerun` marks only existing gates at and after the selected phase `STALE`,
preserves each old gate under `previous`, and moves state back to that phase.
It writes metadata only. For Phase 2, an unchanged `book_fidelity.md` and
optional `chapter-boundaries.json` produce `SKIP (unchanged)` instead of
rewriting chapter artifacts. Do not use a runner's `--force` unless its
documented overwrite behavior is intended.

## Domain Library specific language

* **slug** — set ID of one source book (ex: `davey-2014`). Indexes everything by name.
* **block ID** — `^<slug>-chNN-NNNN` anchor stamped on every substantive chunk in `raw/papers/<slug>/chapters/*.md`.
* **unit** — one extraction work parcel (a chapter, or a ≤2000-line part of one).
* **lane** — one specialist extraction role (definitions, formulas, examples, warnings, empirical context). One agent task per unit × lane.
* **gate** — machine-written JSON under `_meta/extractions/<slug>/gates/` recording PASS/FAIL for a phase. Every phase writes one; every phase checks its predecessor's.
* **STALE gate** — a prior gate invalidated by `domain-library rerun`; its old payload remains nested under `previous`, and `domain-library next` gives the phase command to rebuild it.
* **claim confidence** — `EXTRACTED` is an exact quoted source span, `INFERRED` is a disclosed interpretation marked `⚠` on pages, and `AMBIGUOUS` is retained for Phase 4 human review.
* **embed** — Obsidian transclusion `![[target#^block-id]]` that renders the source passage inside a concept page.

## Maintaining the pipeline

Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). Candidate research belongs in
the maintainer backlog, not in runtime instructions or release claims.

## Planned Upgrades

- Entity pages. The current version records entity mentions in extraction JSON but does not create entity pages; a future version will publish them.

- Automatic run everything mode (no human intervention at page creation).

- Onboarding plugin for popular agent harnesses.

- This pipeline uses GLM-OCR from Z.AI. Support for different OCR providers is coming.

- Automated specialist agents: Library Auditor and Maintenance roles.
