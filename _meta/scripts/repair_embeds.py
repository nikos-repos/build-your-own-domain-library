#!/usr/bin/env python3
"""One-shot (re-runnable) repair: normalize every block embed/link in wiki
pages to the canonical form defined in PAGE_SCHEMA.md "Embeds & Evidence
Links" — vault-absolute chapter path + `#^block-id`.

Handles every malformation class produced by earlier pipeline generations:

1. `![[source#^[id]]]` / `[[source#^[id]]]`  bracket-literal prompt template
2. `![[<id>]]`                               block ID used as a note name
3. `![[source#^id]]`, `![[<book-slug>#^id]]`, `![[ch08#^id]]`,
   partial paths, `.md`-suffixed targets      any non-canonical target

The owning chapter file is looked up by scanning `raw/papers/*/chapters/*.md`
for `^id` anchors. IDs whose anchor exists nowhere are rewritten to inline
code (`` `^id` `` *(unresolved source block)*) so no dead wikilink remains —
explicitly visible rather than silently broken.

Non-embed links get a human-readable alias `|^chNN-NNNN` (Obsidian shows the
alias instead of the long path). Embeds render content, so no alias.

Usage:
    python3 _meta/scripts/repair_embeds.py --wiki . --pages 'concepts/*.md'            # dry run
    python3 _meta/scripts/repair_embeds.py --wiki . --pages 'concepts/*.md' --apply
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from pipeline_common import write_json

BRACKET_RE = re.compile(r"(!?)\[\[([^\]\[#|]+)#\^\[([A-Za-z0-9-]+)\](\]\]\]|\]\])")
ANCHORLESS_RE = re.compile(r"(!?)\[\[([a-z0-9-]+-ch\d+-\d+)\]\]")
BLOCK_LINK_RE = re.compile(r"(!?)\[\[([^\]\[#|]+)#\^([A-Za-z0-9-]+)(?:\|([^\]]*))?\]\]")
ANCHOR_DEF_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)(?=\s|$)", re.MULTILINE)
SHORT_RE = re.compile(r"-(ch\d+-\d+)$")


def build_block_map(wiki: Path) -> dict[str, str]:
    """block_id -> canonical vault-absolute target (no .md), chapters only."""
    refs: dict[str, str] = {}
    for chapters in sorted(wiki.glob("raw/papers/*/chapters")):
        for md in sorted(chapters.glob("*.md")):
            if ".orig." in md.name:
                continue
            ref = str(md.relative_to(wiki))[: -len(".md")].replace("\\", "/")
            for block_id in ANCHOR_DEF_RE.findall(md.read_text(encoding="utf-8", errors="replace")):
                refs.setdefault(block_id, ref)
    return refs


def short_anchor(block_id: str) -> str:
    m = SHORT_RE.search(block_id)
    return m.group(1) if m else block_id


def repair_text(text: str, refs: dict[str, str], stats: Counter, unresolved: Counter) -> str:
    def canonical(embed: bool, block_id: str, current_target: str | None, alias: str | None) -> str:
        ref = refs.get(block_id)
        if ref is None:
            unresolved[block_id] += 1
            stats["unresolved_to_code"] += 1
            return f"`^{block_id}` *(unresolved source block)*"
        bang = "!" if embed else ""
        if embed:
            link = f"{bang}[[{ref}#^{block_id}]]"
        else:
            link = f"{bang}[[{ref}#^{block_id}|{alias or '^' + short_anchor(block_id)}]]"
        if current_target == ref and (embed or alias):
            stats["already_canonical"] += 1
        else:
            stats["rewritten"] += 1
        return link

    def fix_bracket(m: re.Match) -> str:
        return canonical(m.group(1) == "!", m.group(3), None, None)

    def fix_anchorless(m: re.Match) -> str:
        return canonical(m.group(1) == "!", m.group(2), None, None)

    def fix_block_link(m: re.Match) -> str:
        return canonical(m.group(1) == "!", m.group(3), m.group(2).strip(), m.group(4))

    text = BRACKET_RE.sub(fix_bracket, text)
    text = ANCHORLESS_RE.sub(fix_anchorless, text)
    text = BLOCK_LINK_RE.sub(fix_block_link, text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Normalize block embeds/links to canonical chapter-path form")
    ap.add_argument("--wiki", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--pages", nargs="*", default=["concepts/*.md"])
    ap.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    ap.add_argument("--json-out", help="Write repair stats JSON here")
    args = ap.parse_args()

    wiki = Path(args.wiki).resolve()
    refs = build_block_map(wiki)
    stats: Counter = Counter()
    unresolved: Counter = Counter()
    changed_files = 0
    files: list[Path] = []
    for pattern in args.pages:
        files.extend(p for p in wiki.glob(pattern) if p.suffix == ".md")

    for f in sorted(files):
        original = f.read_text(encoding="utf-8", errors="replace")
        repaired = repair_text(original, refs, stats, unresolved)
        if repaired != original:
            changed_files += 1
            if args.apply:
                f.write_text(repaired, encoding="utf-8")

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "known_block_anchors": len(refs),
        "files_scanned": len(files),
        "files_changed": changed_files,
        "stats": dict(stats),
        "unresolved_unique_ids": len(unresolved),
        "unresolved_total_occurrences": sum(unresolved.values()),
        "unresolved_examples": [bid for bid, _n in unresolved.most_common(10)],
    }
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_json(out, summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
