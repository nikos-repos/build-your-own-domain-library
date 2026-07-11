#!/usr/bin/env python3
"""Map Domain Library OCR image assets into chapter markdown.

Canonical Phase 2.4 behavior:
- source OCR paths come from `resolve_ocr_output.py`;
- chapter image assets live centrally under `chapters/images/`;
- chapter markdown refs are rewritten to `images/<filename>`;
- remote/data refs are reportable failures in the gated runner.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<ref>[^)]+)\)")
REMOTE_PREFIXES = ("http://", "https://", "data:")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_KEYS = {"image_path", "img_path", "file_url", "url", "source_url", "content"}


def strip_ref(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    if " " in raw and not raw.startswith(("/", "./", "../")):
        raw = raw.split()[0]
    return raw


def fs_ref(raw: str) -> str:
    return strip_ref(raw).split("#", 1)[0].split("?", 1)[0]


def is_remote(raw: str) -> bool:
    return strip_ref(raw).lower().startswith(REMOTE_PREFIXES)


def looks_like_image_path(value: str) -> bool:
    low = value.lower()
    if low.startswith(("http://", "https://")):
        return False
    path = fs_ref(value)
    return Path(path).suffix.lower() in IMAGE_EXTENSIONS and ("/" in path or path)


def image_basename(value: str) -> str:
    return Path(fs_ref(value)).name


def iter_json_images(obj: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and key in IMAGE_KEYS and looks_like_image_path(value):
                refs.append(value)
            else:
                refs.extend(iter_json_images(value))
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(iter_json_images(item))
    elif isinstance(obj, str):
        for match in IMAGE_RE.finditer(obj):
            ref = match.group("ref")
            if looks_like_image_path(ref):
                refs.append(ref)
    return refs


def collect_ocr_images(json_path: Path, images_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    refs = iter_json_images(data)
    out: dict[str, dict[str, Any]] = {}
    for ref in refs:
        name = image_basename(ref)
        if not name:
            continue
        source = images_dir / name if images_dir else Path(fs_ref(ref))
        out.setdefault(name, {"name": name, "refs": [], "source": str(source), "exists": source.exists() if images_dir else Path(fs_ref(ref)).exists()})
        out[name]["refs"].append(ref)
    if images_dir and images_dir.exists():
        for path in sorted(images_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS and not path.name.endswith(":Zone.Identifier"):
                out.setdefault(path.name, {"name": path.name, "refs": [], "source": str(path), "exists": True})
    return out


def chapter_files(chapters_dir: Path) -> list[Path]:
    return sorted(p for p in chapters_dir.glob("*.md") if ".orig." not in p.name)


def resolve_source(ref: str, md: Path, ocr_images_dir: Path | None) -> tuple[Path | None, str]:
    path_ref = fs_ref(ref)
    if not path_ref:
        return None, "empty ref"
    candidate = Path(path_ref)
    if not candidate.is_absolute():
        candidate = md.parent / path_ref
    if candidate.exists():
        return candidate, "chapter-local"
    if ocr_images_dir:
        name = Path(path_ref).name
        ocr_candidate = ocr_images_dir / name
        if ocr_candidate.exists():
            return ocr_candidate, "ocr-images"
    return None, "missing"


def is_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def map_chapter_images(
    chapters_dir: Path,
    ocr_images_dir: Path | None,
    ocr_json: Path | None = None,
    *,
    central_dir_name: str = "images",
    dry_run: bool = False,
) -> dict[str, Any]:
    if not chapters_dir.exists():
        raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
    central_dir = chapters_dir / central_dir_name
    ocr_images = collect_ocr_images(ocr_json, ocr_images_dir) if ocr_json and ocr_json.exists() else {}
    files = chapter_files(chapters_dir)
    updates: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    remote: list[dict[str, Any]] = []
    resolved: list[dict[str, Any]] = []
    copied = 0
    rewritten = 0
    refs_seen: set[str] = set()

    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")
        changed = False

        def replace(match: re.Match[str]) -> str:
            nonlocal copied, rewritten, changed
            alt = match.group("alt")
            raw_ref = match.group("ref")
            cleaned = strip_ref(raw_ref)
            if is_remote(cleaned):
                remote.append({"file": str(md), "ref": cleaned})
                return match.group(0)
            source, reason = resolve_source(cleaned, md, ocr_images_dir)
            name = image_basename(cleaned)
            if not source or not name:
                missing.append({"file": str(md), "ref": cleaned, "reason": reason})
                return match.group(0)
            refs_seen.add(name)
            target = central_dir / name
            new_ref = f"{central_dir_name}/{name}"
            if not dry_run:
                central_dir.mkdir(parents=True, exist_ok=True)
                if source.resolve() != target.resolve() and (not target.exists() or target.stat().st_size == 0):
                    shutil.copy2(source, target)
                    copied += 1
            if cleaned != new_ref:
                rewritten += 1
                changed = True
                updates.append({"file": str(md), "old_ref": cleaned, "new_ref": new_ref, "source": str(source), "target": str(target)})
                return f"![{alt}]({new_ref})"
            resolved.append({"file": str(md), "ref": cleaned, "resolved": str(target if cleaned == new_ref else source)})
            return match.group(0)

        new_text = IMAGE_RE.sub(replace, text)
        if changed and not dry_run:
            md.write_text(new_text, encoding="utf-8")

    unreferenced_ocr = sorted(name for name in ocr_images if name not in refs_seen)
    return {
        "status": "PASS" if not missing and not remote else "FAIL",
        "chapters_dir": str(chapters_dir),
        "central_images_dir": str(central_dir),
        "chapter_files": len(files),
        "ocr_images_dir": str(ocr_images_dir) if ocr_images_dir else "",
        "ocr_json": str(ocr_json) if ocr_json else "",
        "ocr_image_count": len(ocr_images),
        "chapter_image_refs": len(refs_seen) + len(missing) + len(remote),
        "copied": copied,
        "rewritten": rewritten,
        "missing": len(missing),
        "remote_refs": len(remote),
        "missing_refs": missing,
        "remote": remote,
        "updates": updates,
        "unreferenced_ocr_images": unreferenced_ocr,
        "dry_run": dry_run,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Copy/rebase OCR image refs into chapter-local images directory")
    ap.add_argument("--slug", required=True, help="Book slug")
    ap.add_argument("--images-dir", required=True, help="Resolved OCR imgs/ directory")
    ap.add_argument("--json-output", required=True, help="Resolved OCR JSON output file")
    ap.add_argument("--chapters-dir", required=True, help="Chapters directory")
    ap.add_argument("--central-dir-name", default="images", help="Chapter image directory name; default: images")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = map_chapter_images(
        Path(args.chapters_dir),
        Path(args.images_dir) if args.images_dir else None,
        Path(args.json_output) if args.json_output else None,
        central_dir_name=args.central_dir_name,
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Image mapping: refs={result['chapter_image_refs']} copied={result['copied']} rewritten={result['rewritten']} missing={result['missing']} remote={result['remote_refs']}")
        if result["ocr_image_count"]:
            print(f"OCR images: {result['ocr_image_count']} unreferenced={len(result['unreferenced_ocr_images'])}")
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
