#!/usr/bin/env python3
"""Prune recreatable OCR bulk for a book (approved: audit T18 / OQ7).

Deletes, per slug:
- raw/papers/<slug>/glmocr_output/pdf_chunks/   (re-derivable from archive PDF)
- raw/papers/<slug>/split-pdfs/                 (legacy splitter output)
- raw/papers/<slug>/split-pdfs-pypdf/           (legacy splitter output)

Hard gate — prunes ONLY when the book's text is durably extracted:
an archived source PDF exists in raw/papers/<slug>/archive/ AND either the
Phase 1.5 gate is PASS or the book is LEGACY_FROZEN with book_fidelity.md
or a book markdown present.

Dry run by default; pass --apply to delete. Logs to log.md on apply.

Usage:
    python3 _meta/scripts/prune_raw.py --slug <slug> [--apply]
    python3 _meta/scripts/prune_raw.py --all [--apply]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import pipeline_common

PRUNE_DIRS = ["glmocr_output/pdf_chunks", "split-pdfs", "split-pdfs-pypdf"]


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def gate_ok(wiki: Path, slug: str) -> tuple[bool, str]:
    book = wiki / "raw" / "papers" / slug
    archive_pdfs = list((book / "archive").glob("*.pdf")) if (book / "archive").exists() else []
    if not archive_pdfs:
        return False, "no archived source PDF in archive/"
    gate = wiki / "_meta" / "extractions" / slug / "gates" / "phase-1.5.json"
    if gate.exists():
        try:
            if json.loads(gate.read_text(encoding="utf-8")).get("status") == "PASS":
                return True, "phase-1.5 gate PASS + archived PDF"
        except json.JSONDecodeError:
            pass
    state_file = wiki / "_meta" / "extractions" / slug / "pipeline-state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
        if state.get("status") == "LEGACY_FROZEN":
            has_text = (book / "book_fidelity.md").exists() or (book / "book.md").exists() or (book / f"{slug}.md").exists()
            if has_text:
                return True, "LEGACY_FROZEN + archived PDF + extracted book markdown"
            return False, "LEGACY_FROZEN but no extracted book markdown found"
    return False, "no phase-1.5 PASS gate and not LEGACY_FROZEN"


def prune_slug(wiki: Path, slug: str, apply: bool) -> dict:
    ok, reason = gate_ok(wiki, slug)
    row = {"slug": slug, "eligible": ok, "reason": reason, "pruned": [], "freed_bytes": 0}
    if not ok:
        return row
    book = wiki / "raw" / "papers" / slug
    for rel_dir in PRUNE_DIRS:
        target = book / rel_dir
        if not target.is_dir():
            continue
        size = dir_size(target)
        row["pruned"].append({"dir": rel_dir, "bytes": size})
        row["freed_bytes"] += size
        if apply:
            shutil.rmtree(target)
    if apply and row["freed_bytes"]:
        pipeline_common.append_log(
            wiki, "delete",
            f"pruned recreatable OCR bulk for `{slug}`: {row['freed_bytes'] / 1e6:.0f} MB ({', '.join(p['dir'] for p in row['pruned'])})",
            "prune_raw.py",
        )
    return row


def main() -> None:
    ap = argparse.ArgumentParser(description="Prune recreatable PDF chunk/split bulk (gated)")
    ap.add_argument("--wiki", default=str(SCRIPT_DIR.parents[1]))
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--slug")
    target.add_argument("--all", action="store_true")
    ap.add_argument("--apply", action="store_true", help="Actually delete (default: dry run)")
    args = ap.parse_args()

    wiki = Path(args.wiki).resolve()
    slugs = [args.slug] if args.slug else sorted(p.name for p in (wiki / "raw" / "papers").iterdir() if p.is_dir())
    rows = [prune_slug(wiki, s, args.apply) for s in slugs]
    total = sum(r["freed_bytes"] for r in rows)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "total_freed_mb": round(total / 1e6, 1),
        "books": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
