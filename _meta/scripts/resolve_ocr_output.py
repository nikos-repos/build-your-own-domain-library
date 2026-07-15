#!/usr/bin/env python3
"""Resolve API GLM-OCR output for the proposed Domain Library pipeline.

This script is intentionally API-only. It normalizes the API OCR output tuple
used by Phase 1.5 and Phase 2.4:

  engine, json_path, markdown_path, images_dir

Supported API layouts include:
  raw/papers/<slug>/glmocr_output/combined.json + book.md
  raw/papers/<slug>/glmocr_output/<run>/<run>.json + <run>.md + imgs/
  raw/papers/<slug>/glmocr_output/<slug>/<slug>.json + <slug>.md + imgs/
  raw/papers/<slug>/glmocr_output/<slug>.json + <slug>.md + imgs/
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from domain_library.paths import default_wiki
from typing import Any
from urllib.parse import unquote, urlparse

DEPRECATED_NAMES = {"book_content_list.json", "middle.json", "layout.json"}
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WIKI = Path(os.environ.get("WIKI_PATH", default_wiki()))
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_URL_RE = re.compile(r"https?://[^\s\"'<>)]*", re.IGNORECASE)


def _is_image_url(value: str) -> bool:
    if not isinstance(value, str) or not value.lower().startswith(("http://", "https://")):
        return False
    low = value.lower()
    parsed = urlparse(value)
    path = unquote(parsed.path).lower()
    suffix = Path(path).suffix
    return (
        suffix in IMAGE_EXTENSIONS
        or "ocr/crop" in path
        or "ocr%2fcrop" in low
        or "/crop/" in path
        or "maas-watermark" in parsed.netloc.lower()
    )


def _string_has_image_ref(value: str) -> bool:
    if any(tok in value.lower() for tok in ["imgs/", "images/"]):
        return True
    return any(_is_image_url(match.group(0).rstrip("'\".,;)")) for match in IMAGE_URL_RE.finditer(value))


def _has_image_refs(obj: Any) -> bool:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str):
                if k in {"image", "image_path", "img_path", "file_url", "url", "source_url", "content"} and _string_has_image_ref(v):
                    return True
                if _string_has_image_ref(v):
                    return True
            if _has_image_refs(v):
                return True
    elif isinstance(obj, list):
        return any(_has_image_refs(v) for v in obj)
    return False


def _json_has_image_refs(path: Path) -> bool:
    try:
        return _has_image_refs(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return False

def _layout_pages(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        details = obj.get("layout_details")
        if details is None and isinstance(obj.get("result"), dict):
            details = obj["result"].get("layout_details")
        obj = details
    if not isinstance(obj, list) or not obj:
        return []
    if isinstance(obj[0], dict):
        return [obj]
    if isinstance(obj[0], list):
        return [page for page in obj if isinstance(page, list)]
    return []


def _valid_ocr_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if isinstance(data, list):
        return bool(data)
    if not isinstance(data, dict):
        return False
    if data.get("ok") is False:
        return False
    if data.get("ok") is True:
        return bool(str(data.get("text") or "").strip() or _layout_pages(data))
    if isinstance(data.get("chunks"), list):
        chunks = data["chunks"]
        if not chunks or data.get("failures"):
            return False
        for chunk in chunks:
            result = chunk.get("result") if isinstance(chunk, dict) else None
            if not isinstance(result, dict) or result.get("ok") is not True:
                return False
            if not (str(result.get("text") or "").strip() or _layout_pages(result)):
                return False
        return True
    return bool(_layout_pages(data))



def _score_json(path: Path, slug: str) -> int:
    if not _valid_ocr_json(path):
        return -10_000
    name = path.name.lower()
    if name in DEPRECATED_NAMES:
        return -10_000
    score = 0
    if "glmocr_output" in path.parts:
        score += 100
    if name == "combined.json":
        score += 80
    if name == f"{slug}.json".lower():
        score += 70
    if name.endswith("_model.json"):
        score += 20
    if path.parent.name == slug:
        score += 10
    if _json_has_image_refs(path):
        score += 5
    return score


def _sibling_markdown(json_path: Path, slug: str) -> Path | None:
    candidates = [
        json_path.with_suffix(".md"),
        json_path.parent / "book.md",
        json_path.parent / f"{slug}.md",
        json_path.parent / f"{json_path.stem}.md",
        json_path.parent.parent / "book.md",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _images_dir(json_path: Path) -> Path | None:
    candidates = [
        json_path.parent / "imgs",
        json_path.parent / "images",
        json_path.parent.parent / "imgs",
        json_path.parent.parent / "images",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    # API batch outputs sometimes place combined.json at glmocr_output/ while
    # assets live under one or more run subdirectories. Prefer the first
    # non-empty descendant imgs/images directory rather than failing the gate.
    root = json_path.parent
    descendant_dirs = sorted(
        [p for p in root.rglob("*") if p.is_dir() and p.name.lower() in {"imgs", "images"}],
        key=lambda p: (0 if any(p.iterdir()) else 1, len(p.parts), str(p)),
    )
    return descendant_dirs[0] if descendant_dirs else None


def resolve(slug: str, wiki: Path = DEFAULT_WIKI) -> dict[str, Any]:
    raw_root = wiki / "raw" / "papers" / slug
    if not raw_root.exists():
        raise FileNotFoundError(f"raw paper directory not found: {raw_root}")

    output_root = raw_root / "glmocr_output"
    search_roots = [output_root] if output_root.exists() else [raw_root]
    jsons: list[Path] = []
    for root in search_roots:
        jsons.extend(p for p in root.rglob("*.json") if p.name.lower() not in DEPRECATED_NAMES)

    if not jsons:
        raise FileNotFoundError(f"no API GLM-OCR JSON found under {raw_root}")

    ranked = sorted(jsons, key=lambda p: (_score_json(p, slug), -len(p.parts)), reverse=True)
    json_path = ranked[0]
    if _score_json(json_path, slug) < 0:
        raise FileNotFoundError(f"no valid API GLM-OCR JSON found under {raw_root}")
    md_path = _sibling_markdown(json_path, slug)
    img_dir = _images_dir(json_path)
    has_image_refs = _json_has_image_refs(json_path)

    result = {
        "engine": "glm-ocr-api",
        "slug": slug,
        "wiki": str(wiki),
        "json_path": str(json_path),
        "markdown_path": str(md_path) if md_path else "",
        "images_dir": str(img_dir) if img_dir else "",
        "has_image_refs": has_image_refs,
        "images_dir_required": has_image_refs,
        "warnings": [],
    }
    if not md_path:
        result["warnings"].append("markdown output not found next to resolved JSON")
    if has_image_refs and not img_dir:
        result["warnings"].append("JSON appears to reference images, but no imgs/ or images/ directory was found")
    if has_image_refs and img_dir and not any(img_dir.iterdir()):
        result["warnings"].append("JSON appears to reference images, but the resolved imgs/images directory is empty")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Resolve API GLM-OCR output tuple")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--shell", action="store_true", help="emit shell exports")
    args = ap.parse_args()
    result = resolve(args.slug, Path(args.wiki))
    if args.shell:
        print(f"export OCR_ENGINE={result['engine']!r}")
        print(f"export OCR_JSON={result['json_path']!r}")
        print(f"export OCR_MARKDOWN={result['markdown_path']!r}")
        print(f"export OCR_IMAGES={result['images_dir']!r}")
    else:
        print(json.dumps(result, indent=2) if args.json else "\n".join(f"{k}={v}" for k, v in result.items()))

    if result["images_dir_required"] and not result["images_dir"]:
        raise SystemExit(2)
    if result["images_dir_required"] and result["images_dir"] and not any(Path(result["images_dir"]).iterdir()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
