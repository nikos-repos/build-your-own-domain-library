#!/usr/bin/env python3
"""Shared extraction-unit discovery for the proposed Domain Library pipeline.

The unit id is the stable namespace that prevents chapter/part collisions.
Examples:
  ch-08-title.md                 -> unit_id=ch08
  ch-08-title-part2.md           -> unit_id=ch08-part02
  ch-03-title_part01.md          -> unit_id=ch03-part01
  part-001.md                    -> unit_id=ch00-part001

Block IDs remain chapter-scoped (`slug-chNN-####`) for compatibility, but
output directories and specialist unit titles use `unit_id`.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class ExtractionUnit:
    sort_chapter: int
    sort_part: int
    unit_id: str
    chapter_num: int
    part_num: int | None
    filename: str
    chapter_path: str
    output_dir: str


def _parse_unit(path: Path) -> tuple[int, int | None, str] | None:
    name = path.name
    if not name.endswith(".md") or ".orig." in name:
        return None

    # ch-08-title-part2.md, ch-08-title_part01.md, ch08-title.md
    m = re.match(r"(?:ch(?:apter)?[-_]?)?(\d+)(?:[-_].*)?$", path.stem, re.IGNORECASE)
    if path.stem.lower().startswith(("ch", "chapter")) and m:
        ch = int(m.group(1))
        part = None
        part_match = re.search(r"(?:^|[-_])part[-_]?(\d+)$", path.stem, re.IGNORECASE)
        if part_match:
            part = int(part_match.group(1))
        unit = f"ch{ch:02d}" + (f"-part{part:02d}" if part is not None else "")
        return ch, part, unit

    # bare fallback chunks: part-001.md, part_12.md
    fallback = re.match(r"part[-_]?(\d+)$", path.stem, re.IGNORECASE)
    if fallback:
        part = int(fallback.group(1))
        return 0, part, f"ch00-part{part:03d}"

    return None


def discover_units(chapters_dir: str | Path, slug: str = "") -> list[ExtractionUnit]:
    root = Path(chapters_dir)
    units: list[ExtractionUnit] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*.md")):
        parsed = _parse_unit(path)
        if not parsed:
            continue
        ch, part, unit_id = parsed
        if unit_id in seen:
            raise ValueError(f"duplicate extraction unit id {unit_id!r} from {path.name}")
        seen.add(unit_id)
        rel_chapter = str(path)
        output_dir = f"_meta/extractions/{slug}/team-{unit_id}" if slug else f"team-{unit_id}"
        units.append(
            ExtractionUnit(
                sort_chapter=ch,
                sort_part=part or 0,
                unit_id=unit_id,
                chapter_num=ch,
                part_num=part,
                filename=path.name,
                chapter_path=rel_chapter,
                output_dir=output_dir,
            )
        )
    return sorted(units)


def main() -> None:
    ap = argparse.ArgumentParser(description="Discover Domain Library extraction units")
    ap.add_argument("--chapters-dir", required=True)
    ap.add_argument("--slug", default="")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    units = discover_units(args.chapters_dir, args.slug)
    if args.json:
        print(json.dumps([asdict(u) for u in units], indent=2))
    else:
        for u in units:
            part = f" part={u.part_num}" if u.part_num is not None else ""
            print(f"{u.unit_id}\tch={u.chapter_num}{part}\t{u.filename}\t{u.output_dir}")


if __name__ == "__main__":
    main()
