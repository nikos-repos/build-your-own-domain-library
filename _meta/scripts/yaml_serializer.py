#!/usr/bin/env python3
"""
YAML Frontmatter Serializer
===========================
Post-processes sub-agent markdown output to ensure valid YAML frontmatter.
Parses the agent's output, extracts metadata, generates YAML via yaml.safe_dump(),
and reassembles the file. Eliminates quoting errors, colons-in-titles, and other
YAML gotchas.

Usage:
    domain-library run yaml_serializer \
        --input concepts/draft-page.md \
        --output concepts/final-page.md \
        --confidence 0.75 \
        --tier semantic
"""

import argparse
import json
import re
import sys
from pathlib import Path
from domain_library.paths import default_wiki
from datetime import datetime

from domain_library.pipeline import common as pipeline_common

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


def parse_agent_output(content: str) -> dict:
    """Parse a sub-agent's markdown output into structured components."""
    lines = content.split('\n')
    result = {
        "title": "",
        "body_lines": [],
        "classification_predicates": [],
        "relations": [],
        "in_frontmatter": False,
        "frontmatter_done": False,
    }

    for line in lines:
        stripped = line.strip()

        # Detect existing YAML frontmatter
        if stripped == '---' and not result["frontmatter_done"]:
            result["in_frontmatter"] = not result["in_frontmatter"]
            if not result["in_frontmatter"]:
                result["frontmatter_done"] = True
            continue

        if result["in_frontmatter"]:
            # Extract title from existing frontmatter
            if stripped.startswith('title:'):
                result["title"] = stripped.split(':', 1)[1].strip().strip('"').strip("'")
            continue

        # Classification predicates (after frontmatter, before H1)
        if re.match(r'^- (conforms_to|has_status|in_domain|in_precinct)::', stripped):
            result["classification_predicates"].append(line)
            continue

        # Relations section
        if stripped.startswith('## Relations'):
            result["relations"].append(line)
            continue
        if result["relations"] and stripped.startswith('- '):
            result["relations"].append(line)
            continue
        if result["relations"] and not stripped.startswith('- ') and not stripped.startswith('#'):
            # Annotation line for previous relation
            if result["relations"]:
                result["relations"].append(line)
            continue

        # Regular body content
        result["body_lines"].append(line)

    return result


def build_frontmatter(
    title: str,
    confidence: float,
    tier: str,
    author: str = "orchestrator",
    scope: str = "private",
    quality: float = 0.75,
    quality_notes: str = "source-grounded extraction page generated from validated team presentations",
) -> str:
    """Generate YAML frontmatter using yaml.safe_dump for correctness."""
    safe_title = title.strip()

    fm = {
        "title": safe_title,
        "created": datetime.now().strftime("%Y-%m-%d"),
        "updated": datetime.now().strftime("%Y-%m-%d"),
        "confidence": float(confidence),
        "last_reinforced": datetime.now().strftime("%Y-%m-%d"),
        "tier": tier,
        "quality": float(quality),
        "quality_notes": quality_notes,
        "scope": scope,
        "author": author,
    }

    yaml_str = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True)
    lines = yaml_str.splitlines()
    if lines and lines[0].startswith("title:"):
        lines[0] = f"title: {json.dumps(safe_title, ensure_ascii=False)}"
    return "---\n" + "\n".join(lines) + "\n---\n"


def reassemble_page(parsed: dict, frontmatter: str, classification_predicates: list = None) -> str:
    """Reassemble the full page with correct frontmatter."""
    parts = [frontmatter]

    if classification_predicates:
        parts.extend(classification_predicates)
        parts.append("\n")

    # Add body, filtering out any accidental duplicate frontmatter artifacts
    body_started = False
    for line in parsed["body_lines"]:
        stripped = line.strip()
        if not body_started and not stripped:
            continue
        if not body_started and stripped:
            body_started = True
        parts.append(line)

    # Ensure Relations section exists
    if parsed["relations"]:
        parts.append("\n")
        parts.extend(parsed["relations"])
    else:
        parts.append("\n## Relations\n\n")

    return '\n'.join(parts)


def process_file(input_path: Path, output_path: Path, confidence: float, tier: str, author: str, scope: str):
    """Main processing pipeline for a single file."""
    with open(input_path) as f:
        content = f.read()

    parsed = parse_agent_output(content)

    # Use extracted title or fallback to filename
    title = parsed["title"] or input_path.stem.replace('-', ' ').title()

    frontmatter = build_frontmatter(title, confidence, tier, author, scope)

    # Rebuild classification predicates if they were missing
    class_preds = parsed["classification_predicates"]
    if not class_preds:
        class_preds = [
            "- conforms_to::[[concept-form-contract]]\n",
            "- has_status::[[growing]]\n",
            f"- in_domain::[[{pipeline_common.load_domain_config(default_wiki())['tenant']}]]\n",
        ]

    final = reassemble_page(parsed, frontmatter, class_preds)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write(final)

    print(f"Serialized: {input_path} -> {output_path}")
    print(f"  Title: {title}")
    print(f"  Confidence: {confidence}")
    print(f"  Tier: {tier}")


def main():
    parser = argparse.ArgumentParser(description="YAML Frontmatter Serializer")
    parser.add_argument("--input", required=True, help="Input markdown file")
    parser.add_argument("--output", required=True, help="Output markdown file")
    parser.add_argument("--confidence", type=float, default=0.75, help="Confidence score (0.0-1.0)")
    parser.add_argument("--tier", default="semantic", choices=["working", "episodic", "semantic", "procedural"])
    parser.add_argument("--author", default="orchestrator")
    parser.add_argument("--scope", default="private", choices=["private", "shared"])
    args = parser.parse_args()

    process_file(Path(args.input), Path(args.output), args.confidence, args.tier, args.author, args.scope)


if __name__ == "__main__":
    main()
