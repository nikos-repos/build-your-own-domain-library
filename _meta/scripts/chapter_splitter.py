#!/usr/bin/env python3
"""Split `book_fidelity.md` into canonical Domain Library chapter files.

Phase 2 uses this script as a library and a CLI. It never reads raw OCR
markdown. Manual TOC-derived starts belong in `chapter-boundaries.json`; the
split result is written as the canonical `manifest.json`.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from pipeline_common import write_json
from typing import Any


@dataclass(frozen=True)
class Boundary:
    chapter: int
    title: str
    line_start: int
    line_end: int | None = None
    kind: str = "chapter"
    filename: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_title(raw: str) -> str:
    title = re.sub(r"^#+\s*", "", raw).strip()
    title = re.sub(r"<[^>]+>", "", title).strip()
    title = re.sub(r"\*\*(.*?)\*\*", r"\1", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def sanitize_filename(title: str, chapter: int, kind: str = "chapter") -> str:
    safe = re.sub(r"[^\w\s-]", "", title).strip().lower()
    safe = re.sub(r"[-\s]+", "-", safe).strip("-")
    if not safe:
        safe = "untitled"
    safe = safe[:60]
    if kind == "part":
        return f"part-{chapter:03d}-{safe}"
    return f"ch-{chapter:02d}-{safe}"


def unit_id_for(chapter: int, filename: str) -> str:
    part = re.search(r"(?:^|[-_])part[-_]?(\d+)(?:[-_]|$)", Path(filename).stem, re.IGNORECASE)
    if part:
        return f"ch{chapter:02d}-part{int(part.group(1)):02d}"
    return f"ch{chapter:02d}"


def load_canonical_boundaries(path: Path, line_count: int) -> tuple[list[Boundary], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("chapters"), list):
        raise ValueError("chapter-boundaries.json must be an object with a chapters array")

    boundaries: list[Boundary] = []
    for idx, item in enumerate(data["chapters"], start=1):
        if not isinstance(item, dict):
            raise ValueError(f"chapter boundary #{idx} is not an object")
        title = str(item.get("title", "")).strip()
        if not title:
            raise ValueError(f"chapter boundary #{idx} missing title")
        start = int(item.get("line_start", 0))
        if start < 1 or start > line_count:
            raise ValueError(f"chapter boundary {title!r} has invalid line_start {start}")
        end = item.get("line_end")
        line_end = int(end) if end is not None else None
        if line_end is not None and (line_end < start or line_end > line_count):
            raise ValueError(f"chapter boundary {title!r} has invalid line_end {line_end}")
        chapter = int(item.get("chapter", idx))
        kind = str(item.get("kind", "chapter")).strip() or "chapter"
        filename = str(item.get("filename", "")).strip()
        boundaries.append(Boundary(chapter, title, start - 1, line_end, kind, filename))

    boundaries = normalize_boundaries(boundaries, line_count)
    expected = data.get("expected_units")
    if expected is not None and len(boundaries) != int(expected):
        raise ValueError(f"expected_units={expected} but parsed {len(boundaries)} boundaries")
    return boundaries, data


def normalize_boundaries(boundaries: list[Boundary], line_count: int) -> list[Boundary]:
    if not boundaries:
        return []
    ordered = sorted(boundaries, key=lambda b: b.line_start)
    seen_starts: set[int] = set()
    normalized: list[Boundary] = []
    for idx, b in enumerate(ordered):
        if b.line_start in seen_starts:
            raise ValueError(f"duplicate chapter start line {b.line_start + 1}")
        seen_starts.add(b.line_start)
        next_start = ordered[idx + 1].line_start if idx + 1 < len(ordered) else line_count
        end = b.line_end if b.line_end is not None else next_start
        if end > next_start:
            raise ValueError(f"chapter {b.title!r} overlaps following chapter")
        if end <= b.line_start:
            raise ValueError(f"chapter {b.title!r} is empty")
        normalized.append(Boundary(b.chapter, b.title, b.line_start, end, b.kind, b.filename))
    return normalized


def detect_from_doc_titles(lines: list[str]) -> list[Boundary]:
    skip_titles = {
        "acknowledgments",
        "acknowledgements",
        "about the author",
        "contents",
        "index",
        "notes",
        "figures",
        "tables",
    }
    candidates: list[Boundary] = []
    for i, line in enumerate(lines):
        if ":doc_title" not in line:
            continue
        title = ""
        for j in range(i + 1, min(i + 8, len(lines))):
            candidate = clean_title(lines[j])
            if not candidate or candidate.lower().startswith("div align") or candidate.startswith("/"):
                continue
            title = candidate
            break
        if not title or title.lower() in skip_titles:
            continue
        candidates.append(Boundary(len(candidates) + 1, title, i))
    return normalize_boundaries(candidates, len(lines)) if len(candidates) >= 2 else []


def detect_from_chapter_headings(lines: list[str]) -> list[Boundary]:
    patterns = [
        re.compile(r"^#{1,3}\s+Chapter\s+(\d+)[:\s\-]*(.+)?$", re.IGNORECASE),
        re.compile(r"^#{1,3}\s+(\d{1,2})\s+([A-Z][^\n]{2,})$"),
    ]
    candidates: list[Boundary] = []
    seen_chapters: set[int] = set()
    for i, raw in enumerate(lines):
        line = clean_title(raw)
        for pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue
            chapter = int(match.group(1))
            if chapter in seen_chapters:
                break
            title = clean_title(match.group(2) or f"Chapter {chapter}")
            candidates.append(Boundary(chapter, title, i))
            seen_chapters.add(chapter)
            break
    return normalize_boundaries(candidates, len(lines)) if len(candidates) >= 2 else []


def detect_from_plain_text(lines: list[str]) -> list[Boundary]:
    pattern = re.compile(r"^Chapter\s+(\d+)[:\s\-]*(.+)?$", re.IGNORECASE)
    candidates: list[Boundary] = []
    seen_chapters: set[int] = set()
    for i, raw in enumerate(lines):
        line = clean_title(raw)
        match = pattern.match(line)
        if not match:
            continue
        chapter = int(match.group(1))
        if chapter in seen_chapters:
            continue
        title = clean_title(match.group(2) or f"Chapter {chapter}")
        candidates.append(Boundary(chapter, title, i))
        seen_chapters.add(chapter)
    return normalize_boundaries(candidates, len(lines)) if len(candidates) >= 2 else []


def detect_from_spaced_ocr(lines: list[str]) -> list[Boundary]:
    pattern = re.compile(r"C\s*H\s*A\s*P\s*T\s*E\s*R\s+(\d+)", re.IGNORECASE)
    candidates: list[Boundary] = []
    seen_chapters: set[int] = set()
    for i, raw in enumerate(lines):
        match = pattern.search(raw)
        if not match:
            continue
        chapter = int(match.group(1))
        if chapter in seen_chapters:
            continue
        title = f"Chapter {chapter}"
        for j in range(i + 1, min(i + 6, len(lines))):
            candidate = clean_title(lines[j])
            if candidate and len(candidate) > 2:
                title = candidate
                break
        candidates.append(Boundary(chapter, title, i))
        seen_chapters.add(chapter)
    return normalize_boundaries(candidates, len(lines)) if len(candidates) >= 2 else []


def detect_boundaries(lines: list[str], boundaries_path: Path | None = None) -> tuple[list[Boundary], str, dict[str, Any]]:
    if boundaries_path:
        if not boundaries_path.exists():
            raise FileNotFoundError(f"chapter boundaries file not found: {boundaries_path}")
        boundaries, source = load_canonical_boundaries(boundaries_path, len(lines))
        return boundaries, "manual-boundaries", source

    detectors = [
        ("glm-doc-title", detect_from_doc_titles),
        ("chapter-heading", detect_from_chapter_headings),
        ("plain-text-chapter", detect_from_plain_text),
        ("spaced-ocr-chapter", detect_from_spaced_ocr),
    ]
    for method, detector in detectors:
        boundaries = detector(lines)
        if boundaries:
            return boundaries, method, {}
    return [], "fallback-required", {}


def quote_yaml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def split_chapters(
    input_path: Path,
    output_dir: Path,
    slug: str,
    boundaries_path: Path | None = None,
    manifest_output: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not input_path.exists() or input_path.stat().st_size == 0:
        raise FileNotFoundError(f"book_fidelity.md not found or empty: {input_path}")
    lines = input_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines:
        raise ValueError(f"book_fidelity.md has no lines: {input_path}")

    if output_dir.exists() and any(output_dir.iterdir()):
        if not force:
            raise FileExistsError(f"chapters directory is non-empty; rerun with --force to replace: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    boundaries, method, source_manifest = detect_boundaries(lines, boundaries_path)
    if not boundaries:
        raise RuntimeError("automatic chapter detection failed; create chapter-boundaries.json from the TOC before splitting")

    written: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    for boundary in boundaries:
        filename = boundary.filename or f"{sanitize_filename(boundary.title, boundary.chapter, boundary.kind)}.md"
        if not filename.endswith(".md"):
            filename = f"{filename}.md"
        if filename in seen_files:
            raise ValueError(f"duplicate output filename {filename}")
        seen_files.add(filename)
        out_path = output_dir / filename
        chunk_lines = lines[boundary.line_start:boundary.line_end]
        if not chunk_lines:
            raise ValueError(f"empty chapter split for {boundary.title!r}")
        unit_id = unit_id_for(boundary.chapter, filename)
        frontmatter = (
            "---\n"
            f"source: {quote_yaml(f'[[{slug}]]')}\n"
            f"chapter: {boundary.chapter}\n"
            f"unit_id: {quote_yaml(unit_id)}\n"
            f"title: {quote_yaml(boundary.title)}\n"
            f"source_lines: {quote_yaml(f'{boundary.line_start + 1}-{boundary.line_end}')}\n"
            'page_range: "unknown"\n'
            f"ingested: {datetime.now().strftime('%Y-%m-%d')}\n"
            "---\n"
        )
        out_path.write_text(frontmatter + "".join(chunk_lines).strip() + "\n", encoding="utf-8")
        try:
            file_ref = str(out_path.relative_to(input_path.parent))
        except ValueError:
            file_ref = str(out_path)
        written.append(
            {
                "chapter": boundary.chapter,
                "unit_id": unit_id,
                "kind": boundary.kind,
                "title": boundary.title,
                "file": file_ref,
                "source_lines": [boundary.line_start + 1, boundary.line_end],
                "lines": len(chunk_lines),
            }
        )

    manifest = {
        "schema_version": 1,
        "slug": slug,
        "source": str(input_path),
        "generated_at": utc_now(),
        "detection_method": method,
        "boundaries_file": str(boundaries_path) if boundaries_path else "",
        "source_manifest": source_manifest,
        "unit_count": len(written),
        "chapters": written,
    }
    if manifest_output:
        write_json(manifest_output, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Split book_fidelity.md into Domain Library chapters")
    parser.add_argument("--input", required=True, help="Path to book_fidelity.md")
    parser.add_argument("--output", required=True, help="Output chapters directory")
    parser.add_argument("--slug", required=True, help="Source slug")
    parser.add_argument("--boundaries", help="Canonical chapter-boundaries.json")
    parser.add_argument("--manifest-output", help="Canonical split manifest output path")
    parser.add_argument("--force", action="store_true", help="Replace an existing non-empty chapters directory")
    args = parser.parse_args()

    try:
        manifest = split_chapters(
            Path(args.input),
            Path(args.output),
            args.slug,
            Path(args.boundaries) if args.boundaries else None,
            Path(args.manifest_output) if args.manifest_output else None,
            args.force,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(json.dumps({"status": "PASS", "chapters": manifest["unit_count"], "detection_method": manifest["detection_method"]}, indent=2))


if __name__ == "__main__":
    main()
