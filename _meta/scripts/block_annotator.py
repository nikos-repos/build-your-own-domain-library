#!/usr/bin/env python3
"""Annotate Domain Library chapter markdown with stable inline block IDs.

Low-level annotator behavior:
- scans chapter-like `*.md` files;
- preserves existing correct block IDs;
- annotates substantive body lines only;
- keeps counters global per chapter number.

Canonical Phase 2.3 orchestration is handled by `library_phase23_blocks.py`.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

BLOCK_RE_TEMPLATE = r"\^{slug}-ch(?P<ch>\d{{2}})-(?P<n>\d{{4,}})\b"


def block_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(BLOCK_RE_TEMPLATE.format(slug=re.escape(slug)))


def chapter_number_from_name(path: Path) -> int | None:
    stem = path.stem
    m = re.match(r"(?:ch(?:apter)?[-_]?)(\d+)", stem, re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.match(r"part[-_]?\d+$", stem, re.IGNORECASE):
        return 0
    return None


def is_bare_fallback_chunk(path: Path) -> bool:
    return bool(re.match(r"part[-_]?\d+$", path.stem, re.IGNORECASE))


def annotatable_files(input_dir: Path, include_fallback: bool = True) -> list[Path]:
    files: list[Path] = []
    for path in sorted(input_dir.glob("*.md")):
        if ".orig." in path.name:
            continue
        ch = chapter_number_from_name(path)
        if ch is None:
            continue
        if is_bare_fallback_chunk(path) and not include_fallback:
            continue
        files.append(path)
    return files


def collect_existing(files: list[Path], slug: str) -> dict[int, int]:
    pat = block_pattern(slug)
    max_seen: dict[int, int] = defaultdict(int)
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pat.finditer(text):
            ch = int(match.group("ch"))
            n = int(match.group("n"))
            max_seen[ch] = max(max_seen[ch], n)
    return max_seen


def should_skip_line(stripped: str, in_frontmatter: bool) -> bool:
    if in_frontmatter:
        return True
    if not stripped or stripped == "\f":
        return True
    if stripped.startswith("#"):
        return True
    if stripped.startswith("```"):
        return True
    # Do not annotate table separator rows; table data rows still get IDs.
    if re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped):
        return True
    return False


def count_substantive_lines(path: Path) -> int:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_frontmatter = False
    frontmatter_done = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not frontmatter_done:
            in_frontmatter = not in_frontmatter
            if not in_frontmatter:
                frontmatter_done = True
            continue
        if should_skip_line(stripped, in_frontmatter):
            continue
        count += 1
    return count


def annotate_file(path: Path, slug: str, ch_num: int, start_counter: int) -> dict[str, Any]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    pat = block_pattern(slug)
    out: list[str] = []
    counter = start_counter
    added = 0
    preserved = 0
    substantive = 0
    in_frontmatter = False
    frontmatter_done = False

    for line in lines:
        stripped = line.strip()
        if stripped == "---" and not frontmatter_done:
            in_frontmatter = not in_frontmatter
            out.append(line)
            if not in_frontmatter:
                frontmatter_done = True
            continue
        if should_skip_line(stripped, in_frontmatter):
            out.append(line)
            continue
        substantive += 1
        if pat.search(line):
            preserved += 1
            out.append(line)
            continue
        counter += 1
        out.append(line.rstrip("\n") + f" ^{slug}-ch{ch_num:02d}-{counter:04d}\n")
        added += 1

    if added:
        path.write_text("".join(out), encoding="utf-8")
    final_text = path.read_text(encoding="utf-8", errors="replace") if added else "".join(out)
    block_ids = [m.group(0)[1:] for m in pat.finditer(final_text)]
    return {
        "file": str(path),
        "chapter": ch_num,
        "added": added,
        "preserved": preserved,
        "substantive_lines": substantive,
        "block_ids": len(block_ids),
        "max_block": counter,
    }


def annotate_directory(input_dir: Path, slug: str, include_fallback: bool = True) -> dict[str, Any]:
    files = annotatable_files(input_dir, include_fallback=include_fallback)
    if not files:
        return {"status": "FAIL", "error": f"No annotatable *.md files found in {input_dir}", "files": []}
    counters = collect_existing(files, slug)
    results: list[dict[str, Any]] = []
    for path in files:
        ch = chapter_number_from_name(path)
        assert ch is not None
        result = annotate_file(path, slug, ch, counters[ch])
        counters[ch] = result["max_block"]
        results.append(result)
    return {
        "status": "PASS",
        "slug": slug,
        "input_dir": str(input_dir),
        "files": results,
        "file_count": len(results),
        "total_added": sum(r["added"] for r in results),
        "total_preserved": sum(r["preserved"] for r in results),
        "total_block_ids": sum(r["block_ids"] for r in results),
        "total_substantive_lines": sum(r["substantive_lines"] for r in results),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Annotate chapter markdown files with Domain Library block IDs")
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-fallback", action="store_true", help="exclude bare part-NNN.md fallback chunks")
    args = ap.parse_args()
    result = annotate_directory(Path(args.input_dir), args.slug, include_fallback=not args.no_fallback)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["status"] != "PASS":
            print(result["error"])
        else:
            for record in result["files"]:
                print(
                    f"{Path(record['file']).name}: ch{record['chapter']:02d}, "
                    f"added={record['added']}, preserved={record['preserved']}, blocks={record['block_ids']}"
                )
            print(f"Total added: {result['total_added']}")
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
