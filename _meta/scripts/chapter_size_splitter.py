#!/usr/bin/env python3
"""Deterministic Phase 3.2 helper for splitting oversized chapter units.

The canonical Domain Library runner calls this helper with zero overlap. Overlap is
intentionally unsupported in the gated path because duplicated lines duplicate
block IDs across extraction units.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PART_SUFFIX_RE = re.compile(r"(?:^|[-_])part[-_]?(\d+)$", re.IGNORECASE)
CHAPTER_RE = re.compile(r"(?:ch(?:apter)?[-_]?)?(\d+)", re.IGNORECASE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def split_frontmatter(lines: list[str]) -> tuple[list[str], list[str]]:
    if not lines or lines[0].strip() != "---":
        return [], lines
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return lines[: idx + 1], lines[idx + 1 :]
    return [], lines


def parse_frontmatter(frontmatter: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in frontmatter[1:-1]:
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            fields[key] = value
    return fields


def quote_yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_source_range(value: str) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\s*-\s*(\d+)", value)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def infer_chapter(path: Path, fallback: str = "0") -> str:
    match = CHAPTER_RE.match(path.stem)
    if match:
        return str(int(match.group(1)))
    return fallback


def unit_id_for_part(path: Path) -> str:
    chapter_match = CHAPTER_RE.match(path.stem)
    part_match = PART_SUFFIX_RE.search(path.stem)
    if not chapter_match or not part_match:
        raise ValueError(f"cannot infer chapter/part unit id from {path.name}")
    return f"ch{int(chapter_match.group(1)):02d}-part{int(part_match.group(1)):02d}"


def part_path_for(path: Path, part_num: int) -> Path:
    if PART_SUFFIX_RE.search(path.stem):
        raise ValueError(f"refusing nested split of already-parted unit: {path.name}")
    suffix = path.suffix or ".md"
    return path.with_name(f"{path.stem}-part{part_num:02d}{suffix}")


def find_split_points(lines: list[str], max_lines: int, split_window: int = 100) -> list[int]:
    """Return body-line slice boundaries with no overlap."""
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    if split_window < 0:
        raise ValueError("split_window must be non-negative")
    if len(lines) <= max_lines:
        return [0, len(lines)]

    points = [0]
    pos = 0
    while pos + max_lines < len(lines):
        target = pos + max_lines
        lower = max(pos + 1, target - split_window)
        best = target
        for idx in range(target, lower - 1, -1):
            if idx > pos and idx <= len(lines) and lines[idx - 1].strip() == "":
                best = idx
                break
        if best <= pos:
            best = target
        points.append(best)
        pos = best
    if points[-1] != len(lines):
        points.append(len(lines))
    return points


def render_part_frontmatter(
    original_fields: dict[str, str],
    original_path: Path,
    part_path: Path,
    part_num: int,
    part_count: int,
    body_start: int,
    body_end: int,
    slug: str = "",
) -> str:
    chapter = original_fields.get("chapter") or infer_chapter(original_path)
    title = original_fields.get("title") or original_path.stem.replace("-", " ").replace("_", " ").strip()
    source = original_fields.get("source") or (f"[[{slug}]]" if slug else "")
    page_range = original_fields.get("page_range", "unknown")
    ingested = original_fields.get("ingested", datetime.now().strftime("%Y-%m-%d"))
    source_range = parse_source_range(original_fields.get("source_lines", ""))
    if source_range:
        start = source_range[0] + body_start
        end = source_range[0] + max(body_end - 1, body_start)
        source_lines = f"{start}-{end}"
    else:
        source_lines = original_fields.get("source_lines", "unknown")

    lines = ["---"]
    if source:
        lines.append(f"source: {quote_yaml(source)}")
    lines.extend(
        [
            f"chapter: {chapter}",
            f"unit_id: {quote_yaml(unit_id_for_part(part_path))}",
            f"title: {quote_yaml(f'{title} (part {part_num:02d})')}",
            f"source_lines: {quote_yaml(source_lines)}",
            f"page_range: {quote_yaml(page_range)}",
            f"ingested: {ingested}",
            f"phase_3_2_split_from: {quote_yaml(original_path.name)}",
            f"phase_3_2_part: {quote_yaml(f'{part_num}/{part_count}')}",
            "---",
        ]
    )
    return "\n".join(lines) + "\n"


def rendered_line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def split_chapter(
    filepath: str | Path,
    max_lines: int = 2000,
    split_window: int = 100,
    dry_run: bool = False,
    slug: str = "",
) -> dict[str, Any]:
    path = Path(filepath)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    total_lines = len(lines)
    report: dict[str, Any] = {
        "source_file": str(path),
        "source_line_count": total_lines,
        "max_lines": max_lines,
        "split_window": split_window,
        "was_split": False,
        "dry_run": dry_run,
        "original_archived": "",
        "parts": [],
    }
    if total_lines <= max_lines:
        return report
    if PART_SUFFIX_RE.search(path.stem):
        raise ValueError(f"refusing nested split of already-parted unit: {path.name}")

    frontmatter, body = split_frontmatter(lines)
    original_fields = parse_frontmatter(frontmatter)
    metadata_budget = 12 if (frontmatter or slug) else 0
    if max_lines <= metadata_budget + 1:
        raise ValueError(f"max_lines={max_lines} leaves no room for chapter body after metadata")
    body_limit = max_lines - metadata_budget
    split_points = find_split_points(body, body_limit, split_window)
    part_count = len(split_points) - 1
    if part_count <= 1:
        return report

    orig_path = path.with_name(f"{path.stem}.orig{path.suffix or '.md'}")
    if orig_path.exists() and not dry_run:
        raise FileExistsError(f"refusing to overwrite existing archive: {orig_path}")

    prepared: list[tuple[Path, str, int, int, int]] = []
    for part_num, (start, end) in enumerate(zip(split_points[:-1], split_points[1:]), start=1):
        part_path = part_path_for(path, part_num)
        if part_path.exists() and not dry_run:
            raise FileExistsError(f"refusing to overwrite existing split part: {part_path}")
        chunk = body[start:end]
        if frontmatter or slug:
            text = render_part_frontmatter(original_fields, path, part_path, part_num, part_count, start, end, slug)
        else:
            text = ""
        text += "".join(chunk)
        if not text.endswith("\n"):
            text += "\n"
        part_lines = rendered_line_count(text)
        if part_lines > max_lines:
            raise RuntimeError(f"split part {part_path.name} has {part_lines} lines; max is {max_lines}")
        prepared.append((part_path, text, part_lines, start + 1, end))

    report["was_split"] = True
    report["original_archived"] = str(orig_path)
    report["parts"] = [
        {
            "part": idx,
            "file": str(part_path),
            "lines": part_lines,
            "source_body_lines": [body_start, body_end],
        }
        for idx, (part_path, _text, part_lines, body_start, body_end) in enumerate(prepared, start=1)
    ]

    if dry_run:
        return report

    path.rename(orig_path)
    for part_path, text, _part_lines, _body_start, _body_end in prepared:
        part_path.write_text(text, encoding="utf-8")
    return report


def collect_chapters(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.md") if ".orig." not in path.name)


def split_directory(directory: Path, max_lines: int, split_window: int, dry_run: bool, slug: str = "") -> dict[str, Any]:
    if not directory.exists():
        raise FileNotFoundError(f"chapters directory not found: {directory}")
    chapters = collect_chapters(directory)
    results = [split_chapter(path, max_lines, split_window, dry_run, slug) for path in chapters]
    return {
        "status": "PASS",
        "generated_at": utc_now(),
        "chapters_dir": str(directory),
        "max_lines": max_lines,
        "overlap": 0,
        "split_window": split_window,
        "dry_run": dry_run,
        "chapter_count": len(chapters),
        "split_count": sum(1 for item in results if item["was_split"]),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Split oversized Domain Library chapter units with zero overlap")
    parser.add_argument("--dir", required=True, help="Chapters directory")
    parser.add_argument("--slug", default="", help="Optional source slug for generated split frontmatter")
    parser.add_argument("--max-lines", type=int, default=2000, help="Maximum lines per split part")
    parser.add_argument("--split-window", type=int, default=100, help="Backward paragraph-search window")
    parser.add_argument("--overlap", type=int, default=0, help="Must be 0; overlapping splits duplicate block IDs")
    parser.add_argument("--dry-run", action="store_true", help="Show the split plan without writing files")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        if args.overlap != 0:
            raise ValueError("overlap must be 0 in the Domain Library pipeline")
        report = split_directory(Path(args.dir), args.max_lines, args.split_window, args.dry_run, args.slug)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print(f"Chapter size check: {report['chapter_count']} chapters, max {args.max_lines} lines, overlap 0")
    if report["split_count"] == 0:
        print("All chapters are under the configured line limit")
    else:
        print(f"Split {report['split_count']} chapter(s)")
        for item in report["results"]:
            if not item["was_split"]:
                continue
            part_names = ", ".join(Path(part["file"]).name for part in item["parts"])
            print(f"{Path(item['source_file']).name} -> {part_names}")


if __name__ == "__main__":
    main()
