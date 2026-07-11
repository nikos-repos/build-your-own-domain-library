#!/usr/bin/env python3
"""
Concept Scoring Layer with Density Metrics
==========================================
Merges and deduplicates extraction JSONs, then scores concepts by:
- Cross-chapter frequency
- Specificity (definitions, examples, formulas, warnings)
- Concept density (concepts_per_100_lines)
- Confidence scores from sub-agents

Usage:
    python3 _meta/scripts/scoring_layer.py merge \
        --dir _meta/extractions/<slug>/ \
        --slug <slug> \
        --output _meta/extractions/<slug>/master-scored.json

    python3 _meta/scripts/scoring_layer.py threshold \
        --input _meta/extractions/<slug>/master-scored.json \
        --min-score 9 \
        --output _meta/extractions/<slug>/master-top56.json
"""

import argparse
import json
import sys
from pathlib import Path
from pipeline_common import write_json
from typing import List, Dict, Any
from collections import defaultdict


def load_extractions(directory: Path) -> List[Dict]:
    """Load schema extraction JSONs from a directory, failing closed on bad JSON."""
    extractions = []
    skip_names = {
        "master-scored.json",
        "master-top.json",
        "master-top-clean.json",
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
    for json_file in sorted(directory.glob("*.json")):
        if json_file.name.startswith("_") or json_file.name in skip_names or json_file.name.endswith("-report.json"):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise RuntimeError(f"could not load extraction JSON {json_file}: {e}") from e
        if isinstance(data, dict):
            extractions.append(data)
        elif isinstance(data, list):
            extractions.extend(data)
        else:
            raise RuntimeError(f"extraction JSON must be object or list: {json_file}")
    if not extractions:
        raise RuntimeError(f"no extraction JSONs found in {directory}")
    return extractions


def normalize_slug(slug: str) -> str:
    """Collapse trivial slug variants so they merge instead of fragmenting
    the graph: possessive markers (gambler-s-ruin -> gambler-ruin) and
    plural tokens (arc-sine-laws -> arc-sine-law)."""
    tokens = [t for t in slug.lower().split("-") if t]
    out = []
    for tok in tokens:
        if tok == "s":  # possessive 's rendered as its own token
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return "-".join(out)


def token_jaccard(a: str, b: str) -> float:
    ta, tb = set(normalize_slug(a).split("-")), set(normalize_slug(b).split("-"))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def near_duplicate_groups(candidate_slugs: List[str], existing_slugs: List[str], jaccard_threshold: float = 0.6) -> List[Dict]:
    """Flag likely duplicates among candidates and against already-published
    concept pages. Same normalized form, containment, or high token overlap."""
    flags: List[Dict] = []
    seen_pairs = set()

    def flag(kind: str, slugs: List[str], existing: List[str], reason: str) -> None:
        key = (tuple(sorted(slugs)), tuple(sorted(existing)))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        flags.append({"kind": kind, "slugs": sorted(slugs), "existing": sorted(existing), "reason": reason})

    norm_existing: Dict[str, List[str]] = {}
    for e in existing_slugs:
        norm_existing.setdefault(normalize_slug(e), []).append(e)

    for i, a in enumerate(candidate_slugs):
        na = normalize_slug(a)
        if na in norm_existing and a not in norm_existing[na]:
            flag("vs-existing", [a], norm_existing[na], "normalizes to the same concept as an existing page")
        for b in candidate_slugs[i + 1 :]:
            nb = normalize_slug(b)
            if na == nb:
                flag("in-batch", [a, b], [], "identical after plural/possessive normalization")
            elif na in nb or nb in na:
                flag("in-batch", [a, b], [], "one slug contains the other")
            elif token_jaccard(a, b) >= jaccard_threshold:
                flag("in-batch", [a, b], [], f"token overlap >= {jaccard_threshold}")
    return flags


def merge_concepts(extractions: List[Dict]) -> Dict[str, Dict]:
    """Merge concepts across chapters, deduplicating by slug."""
    merged = defaultdict(lambda: {
        "slug": "",
        "name": "",
        "definitions": [],
        "examples": [],
        "warnings": [],
        "formulas": [],
        "block_ids": [],
        "cross_references": [],
        "chapters": set(),
        "confidence": 0.0,
        "concepts_per_100_lines": 0.0,
        "source_count": 0
    })

    for ext in extractions:
        chapter = ext.get("chapter", 0)
        chapter_title = ext.get("chapter_title", "")

        for concept in ext.get("concepts", []):
            slug = concept.get("slug", "")
            if not slug:
                continue

            m = merged[slug]
            m["slug"] = slug
            m["name"] = concept.get("name", slug)
            m["definitions"].extend(concept.get("definitions", []))
            m["examples"].extend(concept.get("examples", []))
            m["warnings"].extend(concept.get("warnings", []))
            m["formulas"].extend(concept.get("formulas", []))
            m["block_ids"].extend(concept.get("block_ids", []))
            m["cross_references"].extend(concept.get("cross_references", []))
            m["chapters"].add(chapter)
            m["confidence"] = max(m["confidence"], concept.get("confidence", 0.5))
            m["concepts_per_100_lines"] = max(
                m["concepts_per_100_lines"],
                concept.get("concepts_per_100_lines", 0.0)
            )
            m["source_count"] += 1

    # Second pass: fold trivial slug variants (plural/possessive) into one
    # concept so e.g. arc-sine-law / arc-sine-laws cannot both publish.
    groups: Dict[str, List[str]] = {}
    for slug in merged:
        groups.setdefault(normalize_slug(slug), []).append(slug)
    folded: Dict[str, Dict] = {}
    for _norm, slugs in groups.items():
        rep = sorted(slugs, key=lambda s: (len(s), s))[0]
        base = merged[rep]
        for other in slugs:
            if other == rep:
                continue
            o = merged[other]
            base["definitions"].extend(o["definitions"])
            base["examples"].extend(o["examples"])
            base["warnings"].extend(o["warnings"])
            base["formulas"].extend(o["formulas"])
            base["block_ids"].extend(o["block_ids"])
            base["cross_references"].extend(o["cross_references"])
            base["chapters"] |= o["chapters"]
            base["confidence"] = max(base["confidence"], o["confidence"])
            base["concepts_per_100_lines"] = max(base["concepts_per_100_lines"], o["concepts_per_100_lines"])
            base["source_count"] += o["source_count"]
        if len(slugs) > 1:
            base["merged_slugs"] = sorted(slugs)
        folded[rep] = base

    # Convert sets to lists for JSON serialization
    for slug, data in folded.items():
        data["chapters"] = sorted(data["chapters"])
        data["block_ids"] = sorted(set(data["block_ids"]))
        data["cross_references"] = sorted(set(data["cross_references"]))

    return folded


def score_concept(data: Dict) -> int:
    """Score a merged concept. Returns integer score (0+)."""
    score = 0

    # Specificity bonuses
    if data.get("definitions"):
        score += 3
    if data.get("examples"):
        score += 3
    if data.get("formulas"):
        score += 2
    if data.get("warnings"):
        score += 2
    if data.get("cross_references"):
        score += 1

    # Cross-chapter frequency
    chapter_count = len(data.get("chapters", []))
    if chapter_count >= 2:
        score += 1
    if chapter_count >= 3:
        score += 1

    # Density bonus (richly discussed concepts)
    density = data.get("concepts_per_100_lines", 0.0)
    if density >= 2.0:
        score += 1
    if density >= 4.0:
        score += 1

    # Confidence bonus (sub-agent rated it highly)
    confidence = data.get("confidence", 0.5)
    if confidence >= 0.8:
        score += 1

    # Source count bonus (appears in many extraction files)
    if data.get("source_count", 1) >= 2:
        score += 1

    return score


def score_all(merged: Dict[str, Dict]) -> List[Dict]:
    """Score all concepts and return sorted list."""
    scored = []
    for slug, data in merged.items():
        data["score"] = score_concept(data)
        scored.append(data)

    scored.sort(key=lambda x: (-x["score"], x["slug"]))
    return scored


def threshold(scored: List[Dict], min_score: int, top_n: int = None) -> List[Dict]:
    """Filter concepts by minimum score or top N."""
    filtered = [c for c in scored if c["score"] >= min_score]
    if top_n:
        filtered = filtered[:top_n]
    return filtered


def main():
    parser = argparse.ArgumentParser(description="Concept Scoring Layer")
    subparsers = parser.add_subparsers(dest="command")

    p_merge = subparsers.add_parser("merge", help="Merge and score all extractions")
    p_merge.add_argument("--dir", required=True, help="Directory with extraction JSONs")
    p_merge.add_argument("--slug", required=True, help="Source slug")
    p_merge.add_argument("--output", required=True, help="Output JSON file")

    p_thresh = subparsers.add_parser("threshold", help="Filter by score threshold")
    p_thresh.add_argument("--input", required=True, help="Input scored JSON")
    p_thresh.add_argument("--min-score", type=int, default=9, help="Minimum score")
    p_thresh.add_argument("--top-n", type=int, help="Limit to top N concepts")
    p_thresh.add_argument("--output", required=True, help="Output JSON file")

    args = parser.parse_args()

    if args.command == "merge":
        extractions = load_extractions(Path(args.dir))
        print(f"Loaded {len(extractions)} extraction files")

        merged = merge_concepts(extractions)
        print(f"Merged into {len(merged)} unique concepts")

        scored = score_all(merged)
        print(f"Scoring complete. Top 5:")
        for c in scored[:5]:
            print(f"  {c['slug']}: score={c['score']}, chapters={len(c['chapters'])}, density={c['concepts_per_100_lines']:.2f}")

        output = {
            "slug": args.slug,
            "total_concepts": len(scored),
            "concepts": scored
        }

        write_json(Path(args.output), output)
        print(f"Written to {args.output}")

    elif args.command == "threshold":
        with open(args.input) as f:
            data = json.load(f)

        scored = data.get("concepts", [])
        filtered = threshold(scored, args.min_score, args.top_n)

        print(f"Threshold: score >= {args.min_score}")
        print(f"Filtered: {len(filtered)} / {len(scored)} concepts")

        output = {
            "slug": data["slug"],
            "threshold": args.min_score,
            "total_concepts": len(scored),
            "selected_concepts": len(filtered),
            "concepts": {c["slug"]: c for c in filtered}  # dict for fast lookup
        }

        write_json(Path(args.output), output)
        print(f"Written to {args.output}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
