#!/usr/bin/env python3
"""
fidelity_reconstructor.py — Reconstruct full-fidelity markdown from GLM-OCR output.

Accepts GLM-OCR's JSON output format (per-page region lists) and writes a unified
book_fidelity.md that preserves all content types in document order.

GLM-OCR JSON schema (per page):
  [
    [  // page 0
      {"index": 0, "label": "text",    "content": "...", "bbox_2d": [x1,y1,x2,y2], "native_label": "text"},
      {"index": 1, "label": "table",   "content": "<table>...</table>", "bbox_2d": [...], "native_label": "table"},
      {"index": 2, "label": "formula", "content": "$$\\nLaTeX\\n$$", "bbox_2d": [...], "native_label": "display_formula"},
      {"index": 3, "label": "image",   "content": "", "bbox_2d": [...], "native_label": "chart", "image_path": "imgs/file.jpg"},
    ],
    [...]  // page 1
  ]

Usage:
    python3 _meta/scripts/fidelity_reconstructor.py \\
        --slug example-book \\
        --input output/example-book/example-book.json \\
        --output raw/papers/example-book/book_fidelity.md \\
        [--images-dir output/example-book/imgs] \\
        [--dry-run]

Compared to the retired local-OCR reconstruction path:
  - Reads GLM-OCR JSON (simpler, per-page)
  - Formulas come pre-rendered as LaTeX (no VISION_EQUATION_NEEDED)
  - Tables come as HTML <table> (same format → html_table_converter.py still works)
  - Images saved as imgs/cropped_page{N}_idx{M}.jpg
  - Code blocks detected in text regions via fence markers
  - Header hierarchy inferred from native_label + content patterns
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from pipeline_common import write_json

# Import table converter (works with GLM-OCR HTML tables too)
sys.path.insert(0, str(Path(__file__).parent))
from html_table_converter import convert_html_table


# Block types that may need vision enrichment (GLM-OCR produces LaTeX for formulas,
# so VISION markers are only needed for truly unresolvable images)
VISION_TYPES = set()  # GLM-OCR handles formulas natively!

# Noise types to skip entirely
SKIP_NATIVE_LABELS = {"vision_footnote", "page_number", "number", "header"}


def read_glmocr_json(path: str) -> list[list[dict]]:
    """Read and validate GLM-OCR JSON output.

    Expected format: list of pages, each page is a list of regions.
    Each region: {"index", "label", "content", "bbox_2d", "native_label", ...}
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Accept the GLM-OCR CLI wrapper as well as raw API layout arrays.
    if isinstance(data, dict):
        if isinstance(data.get("layout_details"), list):
            data = data["layout_details"]
        elif isinstance(data.get("result"), dict) and isinstance(data["result"].get("layout_details"), list):
            data = data["result"]["layout_details"]
        elif isinstance(data.get("chunks"), list):
            # Domain Library resumable GLM-OCR wrapper: concatenate each chunk's
            # per-page layout_details while preserving document order.
            pages = []
            for chunk in sorted(data["chunks"], key=lambda c: c.get("start_page", c.get("chunk_index", 0))):
                result = chunk.get("result", {})
                details = result.get("layout_details") if isinstance(result, dict) else None
                if isinstance(details, list):
                    if details and isinstance(details[0], dict):
                        pages.append(details)
                    else:
                        pages.extend(details)
            if pages:
                data = pages
            else:
                print(
                    f"ERROR: Chunk wrapper had no usable layout_details; keys {list(data.keys())}",
                    file=sys.stderr,
                )
                sys.exit(1)
        else:
            print(
                f"ERROR: Expected JSON array or CLI wrapper with layout_details, got object keys {list(data.keys())}",
                file=sys.stderr,
            )
            sys.exit(1)

    if not isinstance(data, list):
        print(f"ERROR: Expected JSON array, got {type(data).__name__}", file=sys.stderr)
        sys.exit(1)

    # Handle both flat list and nested list formats
    if data and isinstance(data[0], dict):
        # Single page or flat list
        data = [data]
    elif data and isinstance(data[0], list):
        # Multi-page nested format
        pass
    else:
        print(f"ERROR: Unexpected JSON structure", file=sys.stderr)
        sys.exit(1)

    return data


def infer_header_level(region: dict) -> int:
    """Infer header nesting level (1-3) from native_label and content patterns."""
    native_label = region.get("native_label", "")
    content = region.get("content", "").strip()

    # Explicit label types
    if native_label == "doc_title":
        return 1
    if native_label == "paragraph_title":
        return 2
    if native_label == "figure_title":
        return 3  # or just italicize

    # Content-based patterns
    if re.match(r"^(chapter|part)\s+\d", content, re.IGNORECASE):
        return 1
    if re.match(r"^\d+\.\d+\.\d", content):
        return 3
    if re.match(r"^\d+\.\d+\s", content):
        return 2

    return 2  # default


def process_table_content(content: str) -> str:
    """Convert HTML table content to pipe markdown."""
    if not content:
        return ""

    if content.strip().startswith("<table") and content.strip().endswith("</table>"):
        md_table = convert_html_table(content)
        if md_table.strip():
            return md_table

    # If not HTML, return as-is (might already be markdown)
    return content


def process_formula_content(content: str) -> str:
    """Ensure formula content is properly formatted LaTeX."""
    content = content.strip()
    if not content:
        return ""

    # Already in display math wrappers
    if content.startswith("$$") and content.endswith("$$"):
        return content
    if content.startswith("\\[") and content.endswith("\\]"):
        return "$$" + content[2:-2] + "$$"

    # Wrap in display math
    return f"$$\n{content}\n$$"


def detect_code_block(content: str) -> bool:
    """Detect if text content is actually a code block."""
    # Triple-backtick markers
    if "```" in content:
        return True
    # Python prompts
    if re.search(r"^>>> ", content, re.MULTILINE):
        return True
    if re.search(r"^\.\.\. ", content, re.MULTILINE):
        return True
    # Code-like patterns
    code_indicators = [
        r"^import \w", r"^from \w+ import", r"^def \w+\(",
        r"^\s*class \w+", r"^\s*for \w+ in", r"^\s*if __name__",
        r"return \w", r"print\(", r"np\.", r"pd\.", r"plt\.",
    ]
    matches = sum(1 for p in code_indicators if re.search(p, content, re.MULTILINE))
    if matches >= 2 and len(content) > 50:
        return True
    return False


def process_page(
    page_idx: int,
    regions: list[dict],
    images_dir: str | None = None,
    slug: str = "",
) -> tuple[list[str], dict]:
    """Process one page of GLM-OCR regions into markdown lines.

    Returns (lines, stats_dict).
    """
    lines: list[str] = []
    stats = {
        "text": 0, "header": 0, "code": 0, "formula": 0,
        "table": 0, "image": 0, "skipped": 0,
        "images_found": 0, "images_missing": 0,
    }

    # Sort by index (reading order)
    sorted_regions = sorted(regions, key=lambda r: r.get("index", 0))

    for region in sorted_regions:
        label = region.get("label", "text")
        native_label = region.get("native_label", label)
        content = region.get("content", "")
        bbox = region.get("bbox_2d", [])
        image_path = region.get("image_path", "")
        idx = region.get("index", 0)

        # Build traceability comment
        bbox_str = ",".join(str(int(b)) for b in bbox) if bbox else ""
        trace = f"<!-- block:{label}:{page_idx}:{bbox_str}:{native_label} -->"

        # Skip noise types
        if native_label in SKIP_NATIVE_LABELS:
            stats["skipped"] += 1
            continue

        # ── Table ──
        if label == "table":
            md_table = process_table_content(content)
            if md_table.strip():
                lines.append("")
                lines.append(trace)
                lines.append(md_table)
                lines.append("<!-- /block -->")
                stats["table"] += 1
            else:
                stats["skipped"] += 1

        # ── Formula ──
        elif label == "formula":
            formatted = process_formula_content(content)
            if formatted:
                lines.append("")
                lines.append(trace)
                lines.append(formatted)
                lines.append("<!-- /block -->")
                stats["formula"] += 1
            else:
                stats["skipped"] += 1

        # ── Image / Chart ──
        elif label == "image" or native_label in ("chart", "image", "seal"):
            lines.append("")
            lines.append(trace)
            if image_path:
                is_remote = str(image_path).lower().startswith(("http://", "https://"))
                if images_dir and not is_remote:
                    full_path = os.path.join(images_dir, os.path.basename(image_path))
                else:
                    full_path = image_path

                if not is_remote and os.path.exists(full_path):
                    stats["images_found"] += 1
                else:
                    stats["images_missing"] += 1

                alt = native_label.capitalize()
                lines.append(f"![{alt}]({image_path})")
            else:
                stats["images_missing"] += 1
                lines.append(f"<!-- MISSING_IMAGE: page {page_idx}, index {idx} -->")
            lines.append("<!-- /block -->")
            stats["image"] += 1

        # ── Header / Title ──
        elif native_label in ("doc_title", "paragraph_title", "figure_title"):
            level = infer_header_level(region)
            if content.strip():
                lines.append("")
                lines.append(trace)
                clean = re.sub(r"^#+\s*", "", content.strip())
                lines.append(f"{'#' * level} {clean}")
                lines.append("<!-- /block -->")
                stats["header"] += 1

        # ── Text (including code detection) ──
        elif label == "text":
            if not content.strip():
                stats["skipped"] += 1
                continue

            # Code block detection
            if detect_code_block(content):
                lines.append("")
                lines.append(trace)
                if "```" not in content:
                    lines.append("```python")
                    lines.append(content)
                    lines.append("```")
                else:
                    lines.append(content)
                lines.append("<!-- /block -->")
                stats["code"] += 1
            else:
                lines.append("")
                lines.append(trace)
                lines.append(content.strip())
                lines.append("<!-- /block -->")
                stats["text"] += 1

        # ── Unknown / catch-all ──
        else:
            if content.strip():
                lines.append("")
                lines.append(f"<!-- unknown:{label}:{native_label} -->")
                lines.append(content.strip())
                lines.append("<!-- /block -->")
                stats["text"] += 1
            else:
                stats["skipped"] += 1

    return lines, stats


def reconstruct(
    pages: list[list[dict]],
    images_dir: str | None = None,
    slug: str = "",
    dry_run: bool = False,
) -> tuple[str, dict]:
    """Reconstruct full-fidelity markdown from GLM-OCR pages."""
    all_lines: list[str] = []
    total_stats = {
        "text": 0, "header": 0, "code": 0, "formula": 0,
        "table": 0, "image": 0, "skipped": 0,
        "images_found": 0, "images_missing": 0,
    }

    for page_idx, page_regions in enumerate(pages):
        lines, stats = process_page(page_idx, page_regions, images_dir, slug)
        all_lines.extend(lines)

        for key in total_stats:
            total_stats[key] += stats.get(key, 0)

    total_stats["total_regions"] = sum(
        len(p) for p in pages
    )
    total_stats["pages"] = len(pages)

    markdown = "\n".join(all_lines)

    if dry_run:
        return "", total_stats

    return markdown, total_stats


def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct full-fidelity markdown from GLM-OCR JSON output"
    )
    parser.add_argument("--slug", required=True, help="Book slug")
    parser.add_argument("--input", required=True,
                        help="Path to GLM-OCR JSON output file")
    parser.add_argument("--output", required=True,
                        help="Output markdown file path")
    parser.add_argument("--images-dir", default=None,
                        help="Path to GLM-OCR imgs/ directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute stats without writing output")
    parser.add_argument("--min-fidelity", type=float, default=0.95,
                        help="Minimum required fidelity score")
    parser.add_argument("--require-images", action="store_true",
                        help="Exit nonzero when image regions lack local image files")
    parser.add_argument("--stats-json",
                        help="Optional machine-readable stats/gate output path")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"📖 GLM-OCR Fidelity Reconstruction: {args.slug}")
    print(f"   Input: {args.input}")

    pages = read_glmocr_json(args.input)
    total_regions = sum(len(p) for p in pages)
    print(f"   Pages: {len(pages)}")
    print(f"   Total regions: {total_regions}")

    markdown, stats = reconstruct(
        pages, args.images_dir, args.slug, args.dry_run
    )


    # Print stats
    print(f"\n{'=' * 60}")
    print("  GLM-OCR Block Type Statistics")
    print(f"{'=' * 60}")
    for key in ("pages", "total_regions", "text", "header", "code",
                "formula", "table", "image", "skipped"):
        print(f"  {key:20s}: {stats.get(key, 0):4d}")

    print(f"\n  Formulas (native LaTeX): {stats['formula']}")
    print(f"    ← No VISION_EQUATION_NEEDED markers needed!")

    print(f"\n  Image verification:")
    print(f"    Found on disk:   {stats['images_found']}")
    print(f"    Missing on disk: {stats['images_missing']}")
    if stats['images_missing'] > 0:
        print(f"\n  ⚠ WARNING: {stats['images_missing']} images missing")

    # Fidelity score
    content_types = ("text", "header", "code", "formula", "table", "image")
    accounted = sum(stats[k] for k in content_types)
    total = stats.get("total_regions", 1)
    content_regions = max(1, total - stats.get("skipped", 0))
    fidelity = accounted / content_regions
    stats["accounted_regions"] = accounted
    stats["content_regions"] = content_regions
    stats["fidelity"] = fidelity
    print(f"\n  Fidelity score: {fidelity:.2%} ({accounted}/{content_regions} content regions)")

    failures = []
    if fidelity < args.min_fidelity:
        failures.append(f"fidelity {fidelity:.2%} below required {args.min_fidelity:.2%}")
    if args.require_images and stats["image"] > 0:
        if not args.images_dir:
            failures.append("image regions present but --images-dir was not provided")
        if stats["images_missing"] > 0:
            failures.append(f"{stats['images_missing']} image regions missing local files")
    stats["gate_status"] = "FAIL" if failures else "PASS"
    stats["gate_failures"] = failures

    if args.stats_json:
        stats_path = Path(args.stats_json)
        write_json(stats_path, stats)

    print(f"{'=' * 60}")

    if args.dry_run:
        print("  (dry run — no files written)")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        raise SystemExit(2)

    if not args.dry_run:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(f"<!-- fidelity_reconstructed: {args.slug} -->\n")
            f.write(f"<!-- engine: GLM-OCR -->\n")
            f.write(f"<!-- pages: {stats['pages']} | "
                    f"regions: {stats['total_regions']} | "
                    f"formulas_native: {stats['formula']} -->\n\n")
            f.write(markdown)
            f.write("\n")

        file_size = os.path.getsize(args.output)
        print(f"   Output: {args.output} ({file_size:,} bytes)")


if __name__ == "__main__":
    main()
