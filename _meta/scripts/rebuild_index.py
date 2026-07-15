#!/usr/bin/env python3
"""Regenerate index.md from the live wiki tree (idempotent).

Rebuilds the "## Extracted Concepts" section from concepts/*.md and the
"Last updated" header line; every other section's entries are preserved
as-is. Run after anything that adds/removes concept pages; audit check
WI-49 enforces full coverage.

Usage:
    domain-library run rebuild_index [--wiki PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from domain_library.paths import default_wiki

SCRIPT_DIR = Path(__file__).resolve().parent

from domain_library.pipeline import common as pipeline_common

SECTION_RE = re.compile(r"^## ", re.MULTILINE)


def rebuild(wiki: Path) -> str:
    index = wiki / "index.md"
    stems = sorted(p.stem for p in (wiki / "concepts").glob("*.md"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if index.exists():
        text = index.read_text(encoding="utf-8", errors="replace")
    else:
        text = "# Domain Library Index\n\n> Content catalog. Read first to find relevant pages.\n> Last updated: |\n\n## Extracted Concepts\n"

    text = re.sub(r"^> Last updated:.*$", f"> Last updated: {today} | {len(stems)} concept pages", text, count=1, flags=re.MULTILINE)

    concepts_block = "## Extracted Concepts\n" + "\n".join(f"- [[{stem}]]" for stem in stems) + "\n"
    m = re.search(r"^## Extracted Concepts\s*$", text, flags=re.MULTILINE)
    if m:
        after = text[m.end():]
        nxt = SECTION_RE.search(after)
        end = m.end() + (nxt.start() if nxt else len(after))
        text = text[: m.start()] + concepts_block + text[end:]
    else:
        text = text.rstrip() + "\n\n" + concepts_block
    return text.rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Regenerate index.md from concepts/")
    ap.add_argument("--wiki", default=str(default_wiki()))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    wiki = Path(args.wiki).resolve()
    new_text = rebuild(wiki)
    if args.dry_run:
        print(new_text)
        return
    (wiki / "index.md").write_text(new_text, encoding="utf-8")
    count = new_text.count("- [[")
    pipeline_common.append_log(wiki, "sync", f"index.md regenerated ({count} linked pages)", "rebuild_index.py")
    print(f"index.md regenerated: {count} links")


if __name__ == "__main__":
    main()
