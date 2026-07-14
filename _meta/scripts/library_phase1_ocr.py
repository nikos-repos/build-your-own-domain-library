#!/usr/bin/env python3
"""Domain Library Phase 1/1.5 API GLM-OCR intake runner.

This is the canonical OCR intake path. It is intentionally
API-only: it calls the GLM-OCR skill CLI, materializes any API crop URLs as
local assets, writes separate Phase 1 and Phase 1.5 gate artifacts, and refuses
to advance on weak OCR, missing assets, or low fidelity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

requests = None
PdfReader = None
PdfWriter = None


def load_runtime_dependencies(wiki: Path) -> None:
    global requests, PdfReader, PdfWriter
    try:
        import requests as requests_mod
    except ImportError:  # pragma: no cover - exercised by operator environment
        print("ERROR: requests is required for GLM-OCR crop download", file=sys.stderr)
        raise SystemExit(2)
    try:
        from pypdf import PdfReader as PdfReader_mod, PdfWriter as PdfWriter_mod
    except ImportError:  # pragma: no cover - exercised by operator environment
        print("ERROR: pypdf is required for Phase 1 PDF chunking. Install it before running Phase 1.", file=sys.stderr)
        raise SystemExit(2)
    requests = requests_mod
    PdfReader = PdfReader_mod
    PdfWriter = PdfWriter_mod

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WIKI = Path(os.environ.get("WIKI_PATH", SCRIPT_DIR.parents[1]))
DEFAULT_GLM_CLI = Path(
    os.environ.get(
        "GLM_OCR_CLI",
        str(SCRIPT_DIR.parents[1] / "agents" / "orchestrator" / "skills" / "GLM-OCR" / "scripts" / "glm_ocr_cli.py"),
    )
)
DEFAULT_MAX_BYTES = 45 * 1024 * 1024
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_ASSET_BYTES = 25 * 1024 * 1024
ASSET_HOST_SUFFIXES = ("bigmodel.cn", "bigmodel.com", "ufileos.com")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_URL_RE = re.compile(r"https?://[^\s\"'<>)]*", re.IGNORECASE)
IMAGE_LABELS = {"image", "chart", "seal", "figure"}


from pipeline_common import (  # shared plumbing — audit T10
    extraction_root,
    gate_path,
    rel,
    resolve_path,
    state_path,
    utc_now,
    validate_slug,
    write_gate,
    write_json,
)
import pipeline_common

RUNNER = "library_phase1_ocr.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def result_text(result: dict[str, Any]) -> str:
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text
    raw = result.get("result")
    if isinstance(raw, dict):
        md = raw.get("md_results") or raw.get("markdown")
        if isinstance(md, str) and md.strip():
            return md
    return ""


def layout_pages(result: dict[str, Any]) -> list[list[dict[str, Any]]]:
    details = result.get("layout_details")
    raw = result.get("result")
    if details is None and isinstance(raw, dict):
        details = raw.get("layout_details")
    if not isinstance(details, list) or not details:
        return []
    if isinstance(details[0], dict):
        return [details]  # one flat page/region list
    if isinstance(details[0], list):
        return [page for page in details if isinstance(page, list)]
    return []


def valid_ocr_result(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 100:
        return False
    try:
        data = load_json(path)
    except Exception:
        return False
    if not isinstance(data, dict) or data.get("ok") is not True:
        return False
    return bool(result_text(data).strip() or layout_pages(data))


def write_range(reader: PdfReader, start0: int, end0: int, path: Path) -> None:
    writer = PdfWriter()
    for page_idx in range(start0, end0):
        writer.add_page(reader.pages[page_idx])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        writer.write(fh)


def make_chunks(reader: PdfReader, chunks_dir: Path, max_pages: int, max_bytes: int) -> list[tuple[int, int, int, Path]]:
    chunks: list[tuple[int, int, int, Path]] = []
    page_count = len(reader.pages)
    consumed = 0
    chunk_idx = 1
    while consumed < page_count:
        lo = consumed + 1
        hi = min(page_count, consumed + max_pages)
        while True:
            out = chunks_dir / f"book-pages-{lo:04d}-{hi:04d}.pdf"
            if not out.exists() or out.stat().st_size == 0:
                write_range(reader, lo - 1, hi, out)
            if out.stat().st_size <= max_bytes or hi == lo:
                break
            out.unlink(missing_ok=True)
            hi = max(lo, lo + (hi - lo) // 2 - 1)
        if out.stat().st_size > max_bytes:
            raise RuntimeError(f"single-page chunk exceeds byte gate: {out} ({out.stat().st_size} bytes)")
        chunks.append((chunk_idx, lo, hi, out))
        chunk_idx += 1
        consumed = hi
    return chunks


def is_image_url(value: str) -> bool:
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


def image_urls_in_string(value: str) -> list[str]:
    urls: list[str] = []
    for match in IMAGE_URL_RE.finditer(value):
        url = match.group(0).rstrip("'\".,;)")
        if is_image_url(url):
            urls.append(url)
    return urls


def collect_image_urls(obj: Any) -> set[str]:
    urls: set[str] = set()
    if isinstance(obj, str):
        urls.update(image_urls_in_string(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            urls.update(collect_image_urls(value))
    elif isinstance(obj, list):
        for item in obj:
            urls.update(collect_image_urls(item))
    return urls


def first_image_source(region: dict[str, Any]) -> str:
    for key in ("image_path", "source_url", "file_url", "url", "content"):
        value = region.get(key)
        if isinstance(value, str):
            if is_image_url(value):
                return value
            urls = image_urls_in_string(value)
            if urls:
                return urls[0]
    return ""


def is_image_region(obj: dict[str, Any]) -> bool:
    label = str(obj.get("label", "")).lower()
    native = str(obj.get("native_label", "")).lower()
    return label in IMAGE_LABELS or native in IMAGE_LABELS or bool(first_image_source(obj))


def image_extension(url: str) -> str:
    suffix = Path(unquote(urlparse(url).path)).suffix.lower()
    return suffix if suffix in IMAGE_EXTENSIONS else ".png"


def asset_name(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    return f"crop-{digest}{image_extension(url)}"


def validate_asset_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host == suffix or host.endswith(f".{suffix}") for suffix in ASSET_HOST_SUFFIXES):
        raise ValueError(f"crop URL must use HTTPS on an allowed provider host: {url}")


def download_assets(urls: set[str], images_dir: Path, timeout: float, max_bytes: int = DEFAULT_MAX_ASSET_BYTES, retries: int = 3) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, str]]]:
    images_dir.mkdir(parents=True, exist_ok=True)
    url_map: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for url in sorted(urls):
        name = asset_name(url)
        target = images_dir / name
        local_ref = f"imgs/{name}"
        url_map[url] = local_ref
        status = "cached"
        if not target.exists() or target.stat().st_size == 0:
            status = "downloaded"
            error = ""
            for attempt in range(retries):
                try:
                    validate_asset_url(url)
                    with requests.get(url, stream=True, timeout=timeout) as resp:
                        validate_asset_url(resp.url)
                        if resp.status_code == 429 or 500 <= resp.status_code < 600:
                            raise RuntimeError(f"transient HTTP {resp.status_code}")
                        if resp.status_code != 200:
                            raise RuntimeError(f"HTTP {resp.status_code}")
                        content_type = resp.headers.get("Content-Type", "").split(";", 1)[0].lower()
                        if not content_type.startswith("image/"):
                            raise RuntimeError(f"unexpected content type {content_type!r}")
                        total = 0
                        with target.open("wb") as fh:
                            for chunk in resp.iter_content(chunk_size=64 * 1024):
                                if not chunk:
                                    continue
                                total += len(chunk)
                                if total > max_bytes:
                                    raise RuntimeError(f"asset exceeds {max_bytes} bytes")
                                fh.write(chunk)
                    error = ""
                    break
                except Exception as exc:
                    target.unlink(missing_ok=True)
                    error = str(exc)
                    if attempt + 1 < retries:
                        time.sleep(2 ** attempt)
            if error:
                failures.append({"url": url, "error": error})
                continue
        if not target.exists() or target.stat().st_size == 0:
            failures.append({"url": url, "error": "download produced empty file"})
            continue
        records.append({"url": url, "path": local_ref, "bytes": target.stat().st_size, "status": status})
    return url_map, records, failures


def file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def enforce_source_identity(raw_root: Path, slug: str, source_hash: str) -> Path:
    manifest = raw_root / "source-manifest.json"
    if manifest.exists():
        existing = load_json(manifest)
        if existing.get("sha256") != source_hash:
            raise RuntimeError(f"slug {slug!r} belongs to a different PDF; run `python library.py restart --slug {slug} --yes` first")
    elif raw_root.exists() and any(raw_root.iterdir()):
        raise RuntimeError(f"slug {slug!r} has pre-manifest artifacts; restart it explicitly before ingesting")
    return manifest


def replace_image_urls(value: str, url_map: dict[str, str]) -> str:
    out = value
    for url, local in url_map.items():
        out = out.replace(url, local)
    return out


def normalize_image_refs(obj: Any, url_map: dict[str, str]) -> Any:
    if isinstance(obj, str):
        return replace_image_urls(obj, url_map)
    if isinstance(obj, list):
        return [normalize_image_refs(item, url_map) for item in obj]
    if not isinstance(obj, dict):
        return obj

    source = first_image_source(obj)
    image_region = is_image_region(obj)
    normalized: dict[str, Any] = {}
    for key, value in obj.items():
        if key == "source_url":
            normalized[key] = value
        elif image_region and key == "content" and isinstance(value, str) and source and value.strip() == source:
            normalized[key] = ""
        else:
            normalized[key] = normalize_image_refs(value, url_map)
    if image_region and source:
        normalized.setdefault("source_url", source)
        normalized["image_path"] = url_map.get(source, normalized.get("image_path", source))
    return normalized


def run_glm_cli(cli: Path, pdf: Path, out: Path) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(cli),
        "--file",
        str(pdf),
        "--return-crop-images",
        "--output",
        str(out),
        "--pretty",
    ]
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, text=True)


def run_fidelity_reconstructor(
    slug: str,
    ocr_json: Path,
    images_dir: Path,
    output: Path,
    stats_json: Path,
    min_fidelity: float,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "fidelity_reconstructor.py"),
        "--slug",
        slug,
        "--input",
        str(ocr_json),
        "--output",
        str(output),
        "--images-dir",
        str(images_dir),
        "--min-fidelity",
        str(min_fidelity),
        "--require-images",
        "--stats-json",
        str(stats_json),
    ]
    print("+ " + " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    return proc


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 1 + 1.5 through API GLM-OCR hard gates")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--pdf", required=True, help="Source PDF path")
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    ap.add_argument("--glm-cli", default=str(DEFAULT_GLM_CLI))
    ap.add_argument("--title", default="")
    ap.add_argument("--author", default="")
    ap.add_argument("--force", action="store_true", help="rerun OCR chunks even when existing chunk JSON is valid")
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--download-timeout", type=float, default=30.0)
    ap.add_argument("--max-asset-bytes", type=int, default=DEFAULT_MAX_ASSET_BYTES)
    ap.add_argument("--min-fidelity", type=float, default=0.95)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = validate_slug(args.slug)
    pdf = Path(args.pdf).expanduser().resolve()
    cli = Path(args.glm_cli).expanduser().resolve()
    if not pdf.exists():
        raise SystemExit(f"source PDF not found: {pdf}")
    if not cli.exists():
        raise SystemExit(f"GLM-OCR CLI not found: {cli}")

    raw_root = wiki / "raw" / "papers" / slug
    glm_root = raw_root / "glmocr_output"
    chunks_dir = glm_root / "pdf_chunks"
    images_dir = glm_root / "imgs"
    gates_dir = wiki / "_meta" / "extractions" / slug / "gates"
    load_runtime_dependencies(wiki)

    source_hash, source_bytes = file_identity(pdf)
    try:
        manifest = enforce_source_identity(raw_root, slug, source_hash)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    raw_root.mkdir(parents=True, exist_ok=True)
    glm_root.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    gates_dir.mkdir(parents=True, exist_ok=True)

    archive = raw_root / "archive"
    archive.mkdir(exist_ok=True)
    archived_pdf = archive / pdf.name
    if not archived_pdf.exists():
        shutil.copy2(pdf, archived_pdf)
    elif file_identity(archived_pdf)[0] != source_hash:
        raise SystemExit(f"archived PDF differs for slug {slug!r}; restart it explicitly")

    reader = PdfReader(str(pdf))
    page_count = len(reader.pages)
    write_json(manifest, {"slug": slug, "archived_pdf": rel(archived_pdf, wiki), "sha256": source_hash, "bytes": source_bytes, "page_count": page_count})
    chunks = make_chunks(reader, chunks_dir, args.max_pages, args.max_bytes)
    print(f"PDF pages: {page_count}; chunks: {len(chunks)}", flush=True)

    chunk_records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    all_assets: list[dict[str, Any]] = []
    all_text: list[str] = []
    all_pages: list[list[dict[str, Any]]] = []

    for chunk_idx, start_page, end_page, chunk_pdf in chunks:
        out_json = glm_root / f"chunk-{chunk_idx:03d}-pages-{start_page:04d}-{end_page:04d}.json"
        if args.force or not valid_ocr_result(out_json):
            if out_json.exists():
                out_json.unlink()
            proc = run_glm_cli(cli, chunk_pdf, out_json)
            if proc.returncode != 0 or not valid_ocr_result(out_json):
                failures.append(
                    {
                        "chunk_index": chunk_idx,
                        "start_page": start_page,
                        "end_page": end_page,
                        "pdf": str(chunk_pdf),
                        "json": str(out_json),
                        "exit_code": proc.returncode,
                        "reason": "GLM-OCR failed or produced invalid JSON",
                    }
                )
                break
        else:
            print(f"OCR skip valid {out_json}", flush=True)

        data = load_json(out_json)
        urls = collect_image_urls(data)
        url_map, assets, asset_failures = download_assets(urls, images_dir, args.download_timeout, args.max_asset_bytes)
        if asset_failures:
            failures.append(
                {
                    "chunk_index": chunk_idx,
                    "start_page": start_page,
                    "end_page": end_page,
                    "pdf": str(chunk_pdf),
                    "json": str(out_json),
                    "reason": "crop-image download failed",
                    "asset_failures": asset_failures,
                }
            )
            break
        normalized = normalize_image_refs(data, url_map)
        write_json(out_json, normalized)
        text = result_text(normalized)
        pages = layout_pages(normalized)
        if text.strip():
            all_text.append(f"\n\n<!-- GLM-OCR chunk {chunk_idx:03d}; pages {start_page}-{end_page} -->\n\n{text}")
        all_pages.extend(pages)
        all_assets.extend(assets)
        chunk_records.append(
            {
                "chunk_index": chunk_idx,
                "start_page": start_page,
                "end_page": end_page,
                "pdf": rel(chunk_pdf, wiki),
                "json": rel(out_json, wiki),
                "ok": True,
                "text_chars": len(text),
                "layout_pages": len(pages),
                "crop_assets": len(assets),
            }
        )

    combined_path = glm_root / "combined.json"
    book_md = glm_root / "book.md"
    combined = {
        "ok": not failures,
        "engine": "glm-ocr-api",
        "phase": "1",
        "slug": slug,
        "title": args.title,
        "author": args.author,
        "source_pdf": rel(archived_pdf, wiki),
        "source_sha256": source_hash,
        "source_bytes": source_bytes,
        "archived_pdf": rel(archived_pdf, wiki),
        "page_count": page_count,
        "chunks": chunk_records,
        "text": "\n".join(all_text).strip() + "\n",
        "layout_details": all_pages,
        "assets": all_assets,
        "failures": failures,
        "error": None if not failures else {"code": "PHASE1_FAILED", "message": failures[-1]["reason"]},
        "generated_at": utc_now(),
    }
    write_json(combined_path, combined)
    book_md.write_text(combined["text"], encoding="utf-8")

    gates: dict[str, str] = {}
    if failures:
        gate = write_gate(
            wiki,
            slug,
            "1",
            "FAIL",
            {
                "source_pdf": rel(archived_pdf, wiki),
                "source_sha256": source_hash,
                "combined_json": rel(combined_path, wiki),
                "failures": failures,
            },
        )
        gates["1"] = rel(gate, wiki)
        write_state(wiki, slug, "FAILED", "1", [], gates)
        raise SystemExit(2)

    phase1_gate = write_gate(
        wiki,
        slug,
        "1",
        "PASS",
        {
            "source_pdf": rel(archived_pdf, wiki),
            "source_sha256": source_hash,
            "source_manifest": rel(manifest, wiki),
            "archived_pdf": rel(archived_pdf, wiki),
            "combined_json": rel(combined_path, wiki),
            "markdown": rel(book_md, wiki),
            "images_dir": rel(images_dir, wiki) if all_assets else "",
            "page_count": page_count,
            "chunks": chunk_records,
            "crop_assets": len(all_assets),
            "max_pages": args.max_pages,
            "max_bytes": args.max_bytes,
        },
    )
    gates["1"] = rel(phase1_gate, wiki)

    from resolve_ocr_output import resolve

    resolved = resolve(slug, wiki)
    if resolved["images_dir_required"] and (not resolved["images_dir"] or not any(Path(resolved["images_dir"]).iterdir())):
        phase15_gate = write_gate(
            wiki,
            slug,
            "1.5",
            "FAIL",
            {"reason": "resolver requires non-empty local images_dir", "resolver": resolved},
        )
        gates["1.5"] = rel(phase15_gate, wiki)
        write_state(wiki, slug, "FAILED", "1.5", ["1"], gates)
        raise SystemExit(2)

    fidelity_output = raw_root / "book_fidelity.md"
    stats_json = gates_dir / "phase-1.5-stats.json"
    proc = run_fidelity_reconstructor(
        slug,
        Path(resolved["json_path"]),
        Path(resolved["images_dir"]) if resolved["images_dir"] else images_dir,
        fidelity_output,
        stats_json,
        args.min_fidelity,
    )
    if proc.returncode != 0:
        phase15_gate = write_gate(
            wiki,
            slug,
            "1.5",
            "FAIL",
            {
                "resolver": resolved,
                "book_fidelity": rel(fidelity_output, wiki),
                "stats_json": rel(stats_json, wiki) if stats_json.exists() else "",
                "exit_code": proc.returncode,
                "stdout_tail": proc.stdout[-4000:],
                "stderr_tail": proc.stderr[-4000:],
            },
        )
        gates["1.5"] = rel(phase15_gate, wiki)
        write_state(wiki, slug, "FAILED", "1.5", ["1"], gates)
        raise SystemExit(proc.returncode)

    stats = load_json(stats_json) if stats_json.exists() else {}
    phase15_gate = write_gate(
        wiki,
        slug,
        "1.5",
        "PASS",
        {
            "resolver": resolved,
            "book_fidelity": rel(fidelity_output, wiki),
            "stats_json": rel(stats_json, wiki),
            "min_fidelity": args.min_fidelity,
            "stats": stats,
        },
    )
    gates["1.5"] = rel(phase15_gate, wiki)
    write_state(wiki, slug, "READY_FOR_2.1", "1.5", ["1", "1.5"], gates)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_1_gate": gates["1"],
                "phase_1_5_gate": gates["1.5"],
                "combined_json": rel(combined_path, wiki),
                "book_fidelity": rel(fidelity_output, wiki),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
