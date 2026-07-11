#!/usr/bin/env python3
"""
latex_slug_filter.py
====================
Remove concept slugs that are LaTeX artifacts (operatorname, quad, overline, etc.)
from scored extraction JSON. Run after scoring_layer.py threshold.

Usage:
    python3 _meta/scripts/latex_slug_filter.py \
        --input _meta/extractions/<slug>/master-top56.json \
        --output _meta/extractions/<slug>/master-top56-clean.json
"""

import argparse
import json
import re
import sys
from pathlib import Path
from pipeline_common import write_json


def is_clean_slug(slug: str) -> bool:
    """Return True if slug is not a LaTeX artifact."""
    if re.search(r'[{}\\$<>]|operatorname|quad|overline|stdtdbtdtd|^\d', slug):
        return False
    if len(slug) < 3:
        return False
    return True


def filter_slugs(input_path: Path, output_path: Path) -> dict:
    """Filter dirty slugs from extraction JSON."""
    with open(input_path) as f:
        data = json.load(f)

    concepts = data.get("concepts", {})
    if isinstance(concepts, dict):
        clean_concepts = {k: v for k, v in concepts.items() if is_clean_slug(k)}
        removed = [k for k in concepts if not is_clean_slug(k)]
    elif isinstance(concepts, list):
        clean_concepts = [c for c in concepts if is_clean_slug(c.get("slug", ""))]
        removed = [c.get("slug", "") for c in concepts if not is_clean_slug(c.get("slug", ""))]
    else:
        clean_concepts = concepts
        removed = []

    data["concepts"] = clean_concepts
    data["_latex_filtered"] = {
        "removed_count": len(removed),
        "removed_slugs": removed[:50]  # cap report
    }

    write_json(output_path, data)

    print(f"Filtered {len(removed)} dirty slugs. Clean output: {output_path}")
    if removed:
        print("Removed:")
        for s in removed[:10]:
            print(f"  - {s}")

    return data


def main():
    parser = argparse.ArgumentParser(description="Filter LaTeX artifact slugs")
    parser.add_argument("--input", required=True, help="Input JSON (e.g., master-top56.json)")
    parser.add_argument("--output", required=True, help="Output filtered JSON")
    args = parser.parse_args()

    filter_slugs(Path(args.input), Path(args.output))


if __name__ == "__main__":
    main()
