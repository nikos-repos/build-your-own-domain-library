#!/usr/bin/env python3
"""
Block-ID Resolvability Checker
==============================
Validates that every block ID referenced in extraction JSONs actually exists
in the annotated chapter files. Catches dead embeds at extraction time,
not during audit.

Usage:
    python3 _meta/scripts/blockid_validator.py \
        --slug example-public-domain-book \
        --extractions _meta/extractions/example-public-domain-book/ \
        --chapters raw/papers/example-public-domain-book/chapters/
"""

import argparse
import json
import re
import sys
from pathlib import Path
from pipeline_common import write_json
from typing import Set, List, Dict


def collect_block_ids_from_chapters(chapters_dir: Path, slug: str) -> Set[str]:
    """Scan all chapter files and collect every block ID present."""
    block_ids = set()
    pattern = re.compile(rf'\^({re.escape(slug)}-ch\d+-\d+)')

    for ch_file in sorted(chapters_dir.glob("*.md")):
        if ".orig." in ch_file.name:
            continue
        with open(ch_file) as f:
            content = f.read()
        for match in pattern.finditer(content):
            block_ids.add(match.group(1))  # capture excludes leading ^

    return block_ids


def collect_block_ids_from_value(value) -> List[str]:
    """Recursively collect block_id/block_ids fields from schema JSON values."""
    found: List[str] = []
    if isinstance(value, dict):
        direct = value.get("block_id")
        if isinstance(direct, str) and direct:
            found.append(direct)
        many = value.get("block_ids")
        if isinstance(many, list):
            found.extend(str(item) for item in many if isinstance(item, str) and item)
        for item in value.values():
            found.extend(collect_block_ids_from_value(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(collect_block_ids_from_value(item))
    return found


def collect_block_ids_from_extractions(extractions_dir: Path) -> Dict[str, List[str]]:
    """Scan all extraction JSONs and collect every block ID referenced."""
    referenced: Dict[str, List[str]] = {}
    skip_names = {
        "master-scored.json",
        "master-top56.json",
        "master-top56-clean.json",
        "phase4-scoring-report.json",
        "phase4-confirmation.json",
        "blockid-validation-report.json",
        "schema-validation-report.json",
        "specialist-verification.json",
        "specialist-dispatch-report.json",
        "presentation-report.json",
        "pipeline-run-manifest.json",
    }
    for json_file in sorted(extractions_dir.glob("*.json")):
        if json_file.name.startswith("_") or json_file.name in skip_names or json_file.name.endswith("-report.json"):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            raise RuntimeError(f"could not load extraction JSON {json_file}: {exc}") from exc

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = []
            for key in ["concepts", "entities", "formulas", "claims"]:
                val = data.get(key, [])
                if isinstance(val, dict):
                    items.extend(val.values())
                elif isinstance(val, list):
                    items.extend(val)
        else:
            raise RuntimeError(f"extraction JSON must be object or list: {json_file}")

        for item in items:
            if isinstance(item, dict):
                for bid in collect_block_ids_from_value(item):
                    referenced.setdefault(bid, []).append(str(json_file))

    return referenced


def validate(slug: str, chapters_dir: Path, extractions_dir: Path) -> dict:
    """Run the full validation and return a report."""
    print(f"Collecting block IDs from chapters: {chapters_dir}")
    chapter_ids = collect_block_ids_from_chapters(chapters_dir, slug)
    print(f"  Found {len(chapter_ids)} block IDs in chapter files")

    print(f"Collecting block IDs from extractions: {extractions_dir}")
    referenced_ids = collect_block_ids_from_extractions(extractions_dir)
    print(f"  Found {len(referenced_ids)} unique referenced block IDs")

    missing = []
    for bid, sources in referenced_ids.items():
        if bid not in chapter_ids:
            missing.append({
                "block_id": bid,
                "sources": list(set(sources))[:5]  # cap at 5 sources
            })

    report = {
        "slug": slug,
        "chapter_block_ids": len(chapter_ids),
        "referenced_block_ids": len(referenced_ids),
        "missing_count": len(missing),
        "missing": missing[:50],  # cap at 50
        "valid": len(missing) == 0
    }

    return report


def main():
    parser = argparse.ArgumentParser(description="Block-ID Resolvability Checker")
    parser.add_argument("--slug", required=True, help="Source slug")
    parser.add_argument("--extractions", required=True, help="Directory with extraction JSONs")
    parser.add_argument("--chapters", required=True, help="Directory with chapter markdown files")
    parser.add_argument("--output", help="Optional: write report JSON to file")
    args = parser.parse_args()

    report = validate(args.slug, Path(args.chapters), Path(args.extractions))

    print("\n" + "=" * 60)
    print(f"Block-ID Validation Report for {args.slug}")
    print("=" * 60)
    print(f"Chapter block IDs:     {report['chapter_block_ids']}")
    print(f"Referenced block IDs:  {report['referenced_block_ids']}")
    print(f"Missing block IDs:     {report['missing_count']}")
    print(f"Valid:                 {report['valid']}")
    print("=" * 60)

    if report["missing"]:
        print("\nMissing block IDs (first 20):")
        for m in report["missing"][:20]:
            print(f"  - {m['block_id']} (from {', '.join(m['sources'])})")

    if args.output:
        write_json(Path(args.output), report)
        print(f"\nReport written to: {args.output}")

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
