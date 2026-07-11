#!/usr/bin/env python3
"""Source-grounding QA for Domain Library concept pages.

Produces two artifacts:
1. lexical-overlap-report.json/md: flags concept pages whose non-quoted
   synthesis has low lexical overlap with the source blocks they cite.
2. image-to-page-coverage.md: maps image refs from image-refs-report.json and
   chapter markdown to concept/team pages that reference them.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from pipeline_common import write_json

# Generic English + wiki-structural stopwords only. Book-specific noise
# tokens (title words, author names) belong in --extra-stopwords, not here.
STOP = {
    "the", "and", "for", "that", "with", "this", "from", "are", "was", "were", "has", "have", "had", "but", "not",
    "into", "its", "their", "they", "them", "his", "her", "she", "you", "your", "our", "can", "will", "would", "could",
    "should", "about", "than", "then", "when", "where", "what", "which", "who", "how", "why", "also", "there", "because",
    "chapter", "evidence", "source", "block",
}
BLOCK_RE = re.compile(r"\^(?P<id>[\w-]+-ch\d{2}-\d+)")
EMBED_OR_EDGE_RE = re.compile(r"\[\[(?P<chapter>[^\]#|]+)#\^(?P<block>[\w-]+-ch\d{2}-\d+)\]\]")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<path>[^)]+)\)")


def words(text: str, extra_stop: frozenset = frozenset()) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", text) if w.lower() not in STOP and w.lower() not in extra_stop and len(w) > 3}


def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def nonquoted_synthesis(text: str) -> str:
    out = []
    for line in strip_frontmatter(text).splitlines():
        s = line.strip()
        if not s or s.startswith(">"):
            continue
        if s.startswith("- extracted_from::") or s.startswith("- `") or s.startswith("> Embed:"):
            continue
        if "![[" in s:
            s = re.sub(r"!\[\[[^\]]+\]\]", "", s)
        out.append(s)
    return "\n".join(out)


def load_blocks(chapters_dir: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for md in sorted(chapters_dir.glob("ch-*.md")):
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            m = BLOCK_RE.search(line)
            if not m:
                continue
            block_id = m.group("id")
            clean = re.sub(r"\s*\^[\w-]+-ch\d{2}-\d+", "", line).strip()
            clean = re.sub(r"^#+\s*", "", clean).strip()
            out[block_id] = {"chapter_file": md.stem, "text": clean}
    return out


def cited_blocks(page_text: str) -> list[str]:
    seen = []
    for m in EMBED_OR_EDGE_RE.finditer(page_text):
        bid = m.group("block")
        if bid not in seen:
            seen.append(bid)
    return seen


def concept_pages_for_slug(wiki: Path, slug: str) -> list[Path]:
    pages = []
    for p in sorted((wiki / "concepts").glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if slug in text:
            pages.append(p)
    return pages


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def lexical_report(wiki: Path, slug: str, chapters_dir: Path, threshold: float, extra_stop: frozenset = frozenset()) -> dict[str, Any]:
    block_map = load_blocks(chapters_dir)
    rows = []
    for page in concept_pages_for_slug(wiki, slug):
        text = page.read_text(encoding="utf-8", errors="replace")
        cids = cited_blocks(text)
        source_text = "\n".join(block_map.get(bid, {}).get("text", "") for bid in cids)
        synth_text = nonquoted_synthesis(text)
        full_overlap = jaccard(words(text, extra_stop), words(source_text, extra_stop))
        synthesis_overlap = jaccard(words(synth_text, extra_stop), words(source_text, extra_stop))
        missing = [bid for bid in cids if bid not in block_map]
        rows.append({
            "page": str(page.relative_to(wiki)),
            "cited_block_ids": cids,
            "cited_block_count": len(cids),
            "missing_block_ids": missing,
            "full_page_overlap": round(full_overlap, 4),
            "synthesis_overlap": round(synthesis_overlap, 4),
            "status": "PASS" if synthesis_overlap >= threshold and not missing else "LOW_OVERLAP" if not missing else "MISSING_BLOCK",
        })
    return {
        "slug": slug,
        "threshold": threshold,
        "pages_checked": len(rows),
        "low_overlap_count": sum(1 for r in rows if r["status"] != "PASS"),
        "rows": rows,
    }


def write_lexical_md(report: dict[str, Any], out: Path) -> None:
    lines = [
        f"# Lexical Overlap Report — `{report['slug']}`",
        "",
        f"Threshold: synthesis overlap ≥ `{report['threshold']}`",
        f"Pages checked: {report['pages_checked']}",
        f"Flagged pages: {report['low_overlap_count']}",
        "",
        "| Status | Page | Cited blocks | Synthesis overlap | Full-page overlap |",
        "|---|---|---:|---:|---:|",
    ]
    for r in report["rows"]:
        lines.append(f"| {r['status']} | `{r['page']}` | {r['cited_block_count']} | {r['synthesis_overlap']:.4f} | {r['full_page_overlap']:.4f} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def normalize_img(path: str) -> str:
    path = path.split("#", 1)[0]
    return Path(path).name


def chapter_image_refs(chapters_dir: Path) -> dict[str, list[dict[str, str]]]:
    out = defaultdict(list)
    for md in sorted(chapters_dir.glob("ch-*.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        for m in IMAGE_RE.finditer(text):
            img = normalize_img(m.group("path"))
            out[img].append({"chapter_file": md.name, "ref": m.group("path")})
    return out


def pages_referencing_images(wiki: Path, slug: str, image_names: list[str]) -> dict[str, dict[str, list[str]]]:
    candidates = list((wiki / "concepts").glob("*.md")) + list((wiki / "_meta" / "extractions" / slug).glob("team-*/*.md"))
    out = {img: {"concept_pages": [], "team_pages": []} for img in image_names}
    for p in candidates:
        text = p.read_text(encoding="utf-8", errors="replace")
        for img in image_names:
            if img in text:
                key = "concept_pages" if "/concepts/" in str(p.resolve()) else "team_pages"
                out[img][key].append(str(p.relative_to(wiki)))
    return out


def image_coverage(wiki: Path, slug: str, chapters_dir: Path, image_report_path: Path | None) -> dict[str, Any]:
    report = json.loads(image_report_path.read_text(encoding="utf-8")) if image_report_path and image_report_path.exists() else {}
    refs = chapter_image_refs(chapters_dir)
    image_names = sorted(refs)
    page_refs = pages_referencing_images(wiki, slug, image_names)
    rows = []
    for img in image_names:
        rows.append({
            "image": img,
            "chapter_refs": refs[img],
            "chapter_ref_count": len(refs[img]),
            "concept_pages": page_refs[img]["concept_pages"],
            "team_pages": page_refs[img]["team_pages"],
            "concept_page_covered": bool(page_refs[img]["concept_pages"]),
            "team_page_covered": bool(page_refs[img]["team_pages"]),
        })
    return {
        "slug": slug,
        "image_refs_report": report,
        "images_in_chapters": len(image_names),
        "concept_page_covered": sum(1 for r in rows if r["concept_page_covered"]),
        "team_page_covered": sum(1 for r in rows if r["team_page_covered"]),
        "rows": rows,
    }


def write_image_md(report: dict[str, Any], out: Path) -> None:
    irr = report.get("image_refs_report", {})
    lines = [
        f"# Image-to-Page Coverage — `{report['slug']}`",
        "",
        "## Source image-ref verification",
        "",
        f"- Chapter files: `{irr.get('chapter_files', 'unknown')}`",
        f"- Local refs: `{irr.get('local_refs', 'unknown')}`",
        f"- Resolved: `{irr.get('resolved', 'unknown')}`",
        f"- Missing: `{irr.get('missing', 'unknown')}`",
        f"- Status: `{irr.get('status', 'unknown')}`",
        "",
        "## Coverage table",
        "",
        f"Images in chapter markdown: `{report['images_in_chapters']}`",
        f"Images referenced by concept pages: `{report['concept_page_covered']}`",
        f"Images referenced by team extraction pages: `{report['team_page_covered']}`",
        "",
        "| Image | Chapter refs | Concept pages | Team pages |",
        "|---|---:|---|---|",
    ]
    for r in report["rows"]:
        cps = ", ".join(f"`{p}`" for p in r["concept_pages"]) or "—"
        tps = ", ".join(f"`{p}`" for p in r["team_pages"][:4])
        if len(r["team_pages"]) > 4:
            tps += f", … +{len(r['team_pages']) - 4}"
        tps = tps or "—"
        lines.append(f"| `{r['image']}` | {r['chapter_ref_count']} | {cps} | {tps} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run lexical overlap and image coverage checks")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--chapters-dir", required=True)
    ap.add_argument("--image-report")
    ap.add_argument("--out-dir")
    ap.add_argument("--threshold", type=float, default=0.12)
    ap.add_argument(
        "--extra-stopwords",
        default="",
        help="Comma-separated book-specific noise tokens (title words, author names) excluded from overlap scoring",
    )
    args = ap.parse_args()
    extra_stop = frozenset(w.strip().lower() for w in args.extra_stopwords.split(",") if w.strip())

    wiki = Path(args.wiki)
    out_dir = Path(args.out_dir) if args.out_dir else wiki / "_meta" / "extractions" / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    lex = lexical_report(wiki, args.slug, Path(args.chapters_dir), args.threshold, extra_stop)
    img = image_coverage(wiki, args.slug, Path(args.chapters_dir), Path(args.image_report) if args.image_report else None)
    write_json(out_dir / "lexical-overlap-report.json", lex)
    write_json(out_dir / "image-to-page-coverage.json", img)
    write_lexical_md(lex, out_dir / "lexical-overlap-report.md")
    write_image_md(img, out_dir / "image-to-page-coverage.md")
    print(json.dumps({
        "lexical_overlap": {"pages_checked": lex["pages_checked"], "low_overlap_count": lex["low_overlap_count"], "threshold": lex["threshold"]},
        "image_coverage": {"images_in_chapters": img["images_in_chapters"], "concept_page_covered": img["concept_page_covered"], "team_page_covered": img["team_page_covered"]},
        "out_dir": str(out_dir),
    }, indent=2))


if __name__ == "__main__":
    main()
