# Build Your Own Domain Library

An academic book ingestion and extraction pipeline for building a markdown knowledge base from PDFs. Inspired by the LLM Wiki pattern proposed by Andrej Karpathy, but revamped in a way that <u>**actually works.**</u> This gated pipeline that turns a raw source document (such as 900+ page books, and academic research articles) into **source-grounded, rich concept pages**.

These are markdown Library pages where every single claim you can see is backed by a click-through embed of the exact source passage.

For me, this system makes tackling advanced subjects feel like a treasure hunt:

Pick a concept that sounds cool → Read the detailed concept page → Navigate back to the full chapter for anything you don't understand → Repeat.

## What the pipeline does

This customizable workflow runs OCR, reconstructs raw source material into structured markdown, splits chapters, assigns stable block IDs to each text chunk, classfies text blocks, dispatches specialist extraction workers, verifies gathered evidence, scores candidate concepts, waits for human review, and writes final `PAGE_SCHEMA.md` compliant pages.

## Who this is for

* Researchers, students, independent scholars, or users new to AI-assisted tools desiring a useful system that isn't just hype.

* Anybody who was disappointed when their "LLM-Wiki" or "AI second-brain" project never actually functioned for reproducible evidence-linked knowledge extraction.

## Quickstart

Clone or this repo then run:

```bash
cd build-your-own-domain-library
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env and replace ZHIPU_API_KEY=replace_me.
.venv/bin/python library.py doctor --full
```

### Configuration and secrets

Customize `_meta/config/domain.json` for your field. Its `lanes` array defines the specialist prompt contracts and expected outputs.

The only repository-owned secret is `ZHIPU_API_KEY` in the root `.env`. The OCR client also reads `GLM_OCR_TIMEOUT` there. Agent runtimes choose their own model and authentication; the repository records the actual runtime, model, task ID, and job ID after dispatch.

## Output and proof

Published pages are written under `concepts/`. A license-attributed mini example result is available in [`examples/demo-library`](examples/demo-library/README.md).

The canonical phase workflow is [`agents/skills/domain-library-ingest-pipeline/SKILL.md`](agents/skills/domain-library-ingest-pipeline/SKILL.md). Page requirements are in [`PAGE_SCHEMA.md`](PAGE_SCHEMA.md), and security guidance is in [`SECURITY.md`](SECURITY.md).

Setup is intended to take only a few minutes after Python and an OCR key are available. Full ingestion time and OCR cost will scale with document size.

## Domain Library specific language

* **slug** — set ID of one source book (ex: `davey-2014`). Indexes everything by name.
* **block ID** — `^<slug>-chNN-NNNN` anchor stamped on every substantive chunk in `raw/papers/<slug>/chapters/*.md`.
* **unit** — one extraction work parcel (a chapter, or a ≤2000-line part of one).
* **lane** — one specialist extraction role (definitions, formulas, examples,warnings, empirical context). One agent task per unit × lane.
* **gate** — machine-written JSON under `_meta/extractions/<slug>/gates/`recording PASS/FAIL for a phase. Every phase writes one; every phase checksits predecessor's.
* **embed** — Obsidian transclusion `![[target#^block-id]]` that renders the source passage inside a concept page.

## Planned Upgrades

- Next verison will publish entity pages. Entity mentions may remain in extraction JSON but no entity pages will be created. 

- Automatic run everything mode (no human intervention at page creation).

- Onboarding plugin for popular agent hanesses.

- This pipeline uses GLM-OCR from Z.AI. Support for different OCR providers is coming.

- Automated specialist agent, Library Auditor and Maintenence, role. 
