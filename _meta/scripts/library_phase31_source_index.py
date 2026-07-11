#!/usr/bin/env python3
"""Domain Library Phase 3.1 deterministic source-index runner."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from extraction_units import ExtractionUnit, discover_units

DEFAULT_WIKI = SCRIPT_DIR.parents[1]
CATEGORIES = [
    "Definitions",
    "Formulas",
    "Examples / Figures",
    "Warnings / Caveats",
    "Historical / Empirical References",
    "Transitional / Structural",
]

DEFINITION_KEYWORDS = [
    "is known as", "is defined as", "denoted", "let ", "we define", "refers to",
    "concept", "notion", "consists of", "main types", "known as", "represents",
    "means ", "signifies", "by definition", "differs from", "is called", "can be defined",
    "is a type of", "is the", "are the", "is an", "are an", "also called",
    "in general", "broadly speaking", "refers to the", "defined as the",
    "can be categorized", "can be classified", "is characterized by",
]
FORMULA_PATTERNS = [
    r"\\tag\{", r"\$\$", r"\\begin\{array\}", r"\\operatorname\*",
    r"\\sum_", r"\\min_", r"\\max_", r"\\int_", r"\\frac\{", r"\\left", r"\\right",
    r"\\begin\{equation\}", r"\\begin\{align\}", r"\\\[", r"\\\]", r"\$[^$]+\$",
    r"\\begin\{gather\}", r"\\begin\{multline\}", r"\\begin\{split\}",
    r"\\sqrt\{", r"\\alpha", r"\\beta", r"\\gamma", r"\\delta", r"\\sigma", r"\\mu",
    r"\\mathbb\{", r"\\mathcal\{", r"\\mathrm\{", r"\\mathbf\{",
]
EXAMPLE_KEYWORDS = [
    "Figure", "Table", "Algorithm", "Example", "Listing", "parameters", "numerical", "simulation",
    "pseudocode", "procedure", "steps", "python", "code", "import ", "def ", "print(",
    "output", "result", "returns", "yield", "plot", "chart", "graph", "visualize",
    "interactive", "candlestick", "time series",
]
WARNING_KEYWORDS = [
    "however", "caution", "limitation", "fragile", "assumes", "contradiction",
    "not confirmed", "differs from", "unlike", "too large", "too many", "too small",
    "only affects", "violation", "penalty", "risk", "danger", "problematic",
    "underestimate", "overestimate", "sensitive", "unstable", "drawback", "shortcoming",
    "important to note", "must be careful", "beware", "warning", "note that",
    "care must", "should not", "cannot be", "may not", "might not", "does not guarantee",
    "it is worth noting", "keep in mind", "be aware", "caveat", "pitfall",
]
# ponytail: generic citation cues only; domain-specific author names can be
# added per-library if classification recall needs a boost.
HISTORICAL_KEYWORDS = [
    "et al.", "study", "empirical", "paper", "work", "framework", "research",
    "according to", "proposed by", "introduced by", "developed by",
    "in their seminal", "classic paper", "well-known", "widely used",
    "first described", "originally published", "prior work", "previous studies",
    "literature", "citation", "reference", "survey",
]
TRANSITIONAL_PHRASES = [
    "the next section", "in this chapter", "in the following", "we will look",
    "let us look", "the following section", "in a nutshell", "to summarize",
    "in summary", "to conclude", "first, ", "second, ", "third, ", "finally, ",
    "lastly, ", "the next chapter", "as mentioned earlier", "as we have seen",
    "we start by", "we then switch", "we now turn", "we next", "before we",
    "after we", "in the previous", "in the next",
]
CODE_DATA_PATTERNS = [
    r"^```\w*\s*$",
    r"^(import |from \S+ import |def |class |print\(|>>> |\.\.\. )",
    r"^[%\w]+\s*=\s*",
    r"^\w+\.\w+\(",
    r"^\w+\(",
    r"^%\w+",
    r"^\d{4}-\d{2}-\d{2}\s+\d",
    r"^\d+\.\d+\s+\d+\.\d+",
    r"^\d+\.\d+$",
    r"^\d+$",
    r"^Epoch\s+\d+",
    r"^['\"]\w+['\"]:\s*['\"\d\[{]",
    r"^\{['\"]\w+['\"]:",
    r"^[\w\-]+,\s*[\w\-]+,",
]
SOURCE_JSON_RE = re.compile(r"<!--\s*source_index_json\s*\n(?P<json>.*?)\n\s*-->", re.DOTALL)


from pipeline_common import (  # shared plumbing — audit T10
    extraction_root,
    gate_path,
    load_state,
    read_json,
    rel,
    resolve_path,
    state_path,
    utc_now,
    write_gate,
    write_json,
)
import pipeline_common

RUNNER = "library_phase31_source_index.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase30(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.0")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.0 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.0 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.0" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.0 complete")
    if state.get("status") not in {"READY_FOR_3.1", "READY_FOR_3.2", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.1: {state.get('status')}")
    return state, gate_data


def classify(text: str) -> str:
    t = text.lower()
    word_count = len(text.split())
    stripped = text.strip()
    for pattern in FORMULA_PATTERNS:
        if re.search(pattern, text):
            return "Formulas"
    for pattern in CODE_DATA_PATTERNS:
        if re.search(pattern, stripped):
            return "Examples / Figures"
    if re.search(r"^(```|\{|\[)\s*$", stripped):
        return "Examples / Figures"
    if re.search(r"^[A-Z][A-Za-z\s\-/]+:\s", stripped) and word_count >= 5:
        return "Definitions"
    if word_count >= 8 and any(keyword.lower() in t for keyword in DEFINITION_KEYWORDS):
        return "Definitions"
    if word_count >= 5 and re.search(r"\b(is defined as|is known as|also called|refers to)\b", t):
        return "Definitions"
    if word_count >= 5 and any(keyword.lower() in t for keyword in WARNING_KEYWORDS):
        return "Warnings / Caveats"
    if any(keyword.lower() in t for keyword in HISTORICAL_KEYWORDS):
        return "Historical / Empirical References"
    if re.search(r"\b(Figure|Table|Algorithm|Listing|Example)\s+[\d\-]+", text):
        return "Examples / Figures"
    if word_count >= 8:
        if any(keyword.lower() in t for keyword in EXAMPLE_KEYWORDS):
            return "Examples / Figures"
        if re.search(r"\d+\.\d+", text) or re.search(r"\d+%", text) or re.search(r"\$\d+", text):
            return "Examples / Figures"
    if word_count <= 3:
        return "Transitional / Structural"
    if re.search(r"^#{1,6}\s+", stripped) or re.search(r"^---+\s*$", stripped):
        return "Transitional / Structural"
    if any(phrase in t for phrase in TRANSITIONAL_PHRASES):
        return "Transitional / Structural"
    if word_count >= 12:
        if re.search(r"\b(is a|are a|refers to|used to|involves|consists of|contains|provides|describes|represents|denotes|signifies)\b", t):
            return "Definitions"
        if re.search(r"\b(such as|for example|e\.g\.|i\.e\.|namely|specifically|in particular|consider the|suppose|assume that)\b", t):
            return "Examples / Figures"
        if re.search(r"\b(should|must|need to|important|note|beware|careful|avoid|ensure|verify|check that)\b", t):
            return "Warnings / Caveats"
        if re.search(r"\b(data|dataset|sample|observation|empirical|measurement|performance|result|finding)\b", t):
            return "Historical / Empirical References"
    return "Transitional / Structural"


def title_for_unit(path: Path, fallback: str) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[:30]:
        if line.strip().startswith("title:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'") or fallback
    for line in lines[:50]:
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip() or fallback
    return fallback


def block_patterns(slug: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    same = re.compile(rf"\^(?P<id>{re.escape(slug)}-ch(?P<ch>\d{{2}})-(?P<n>\d{{4,}}))\b")
    any_like = re.compile(r"\^(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*-ch(?P<ch>\d{1,2})-(?P<n>\d+))\b")
    return same, any_like


def extract_blocks(unit: ExtractionUnit, slug: str) -> tuple[list[dict[str, Any]], list[str]]:
    path = Path(unit.chapter_path)
    same, any_like = block_patterns(slug)
    failures: list[str] = []
    blocks: list[dict[str, Any]] = []
    seen_in_file: set[str] = set()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, line in enumerate(lines, start=1):
        same_matches = list(same.finditer(line))
        same_spans = [m.span() for m in same_matches]
        for match in any_like.finditer(line):
            if any(start <= match.start() and match.end() <= end for start, end in same_spans):
                continue
            failures.append(f"wrong-slug or malformed block ID in {path}:{line_no}: {match.group('id')}")
        for match in same_matches:
            block_id = match.group("id")
            ch = int(match.group("ch"))
            if ch != unit.chapter_num:
                failures.append(f"block ID chapter mismatch in {path}:{line_no}: {block_id} expected ch{unit.chapter_num:02d}")
            if block_id in seen_in_file:
                failures.append(f"duplicate block ID within unit {unit.unit_id}: {block_id}")
            seen_in_file.add(block_id)
            clean = line[: match.start()].strip()
            if not clean:
                clean = line.strip()
            category = classify(clean)
            blocks.append({"block_id": block_id, "line": line_no, "text": clean, "category": category})
    return blocks, failures


def render_source_index(slug: str, unit: ExtractionUnit, blocks: list[dict[str, Any]], title: str) -> str:
    by_category: dict[str, list[dict[str, Any]]] = {category: [] for category in CATEGORIES}
    for block in blocks:
        by_category[block["category"]].append(block)
    payload = {
        "schema_version": 1,
        "slug": slug,
        "unit_id": unit.unit_id,
        "chapter_file": unit.chapter_path,
        "title": title,
        "generated_at": utc_now(),
        "total_block_ids": len(blocks),
        "categories": {category: [b["block_id"] for b in by_category[category]] for category in CATEGORIES},
        "blocks": blocks,
    }
    path = Path(unit.chapter_path)
    lines = [
        f"# Source Index — {unit.unit_id} {title}",
        "",
        f"**Total block IDs indexed:** {len(blocks)}",
        f"**Unit ID:** `{unit.unit_id}`",
        f"**Source:** `{path.name}` ({len(path.read_text(encoding='utf-8', errors='replace').splitlines())} lines, {path.stat().st_size // 1024} KB)",
        "",
    ]
    for category in CATEGORIES:
        lines.extend([f"## {category}", ""])
        if by_category[category]:
            for block in by_category[category]:
                snippet = block["text"].replace("\n", " ")[:160]
                lines.append(f"- [{block['block_id']}] — {json.dumps(snippet, ensure_ascii=False)} (line {block['line']})")
        else:
            lines.append("- none")
        lines.append("")
    lines.extend(["<!-- source_index_json", json.dumps(payload, ensure_ascii=False, sort_keys=True), "-->"])
    return "\n".join(lines).rstrip() + "\n"


def parse_source_index(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = SOURCE_JSON_RE.search(text)
    if not match:
        raise ValueError(f"source_index_json comment missing in {path}")
    data = json.loads(match.group("json"))
    if not isinstance(data, dict):
        raise ValueError(f"source_index_json is not an object in {path}")
    return data


def validate_index(path: Path, unit: ExtractionUnit, chapter_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    data = parse_source_index(path)
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError(f"source index blocks missing in {path}")
    chapter_ids = [b["block_id"] for b in chapter_blocks]
    indexed_ids = [b.get("block_id") for b in blocks if isinstance(b, dict)]
    failures: list[str] = []
    if Counter(chapter_ids) != Counter(indexed_ids):
        missing = sorted((Counter(chapter_ids) - Counter(indexed_ids)).elements())
        extra = sorted((Counter(indexed_ids) - Counter(chapter_ids)).elements())
        if missing:
            failures.append(f"missing indexed block IDs: {missing[:10]}")
        if extra:
            failures.append(f"extra indexed block IDs: {extra[:10]}")
    if len(indexed_ids) != len(set(indexed_ids)):
        failures.append("duplicate block IDs in source index")
    for block in blocks:
        category = block.get("category") if isinstance(block, dict) else None
        if category not in CATEGORIES:
            failures.append(f"invalid category for block {block!r}")
    if data.get("unit_id") != unit.unit_id:
        failures.append(f"unit_id mismatch: {data.get('unit_id')} != {unit.unit_id}")
    return {
        "valid": not failures,
        "failures": failures,
        "indexed_count": len(indexed_ids),
        "chapter_count": len(chapter_ids),
        "category_counts": {category: len(data.get("categories", {}).get(category, [])) for category in CATEGORIES},
    }


def source_index_path(wiki: Path, slug: str, unit: ExtractionUnit) -> Path:
    return wiki / "_meta" / "extractions" / slug / f"team-{unit.unit_id}" / "orchestrator-source-index.md"


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 3.1 deterministic source-index gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    report_path = raw_root / "source-index-report.json"
    gates: dict[str, str] = {}
    completed: list[str] = []
    report: dict[str, Any] = {}
    try:
        state, phase30 = preflight_phase30(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
        units = discover_units(chapters_dir, slug)
        if not units:
            raise RuntimeError(f"no extraction units discovered in {chapters_dir}")

        all_failures: list[str] = []
        unit_reports: list[dict[str, Any]] = []
        all_ids: list[str] = []
        for unit in units:
            vision_log = wiki / "_meta" / "extractions" / slug / f"team-{unit.unit_id}" / "orchestrator-vision-enrichment.md"
            if not vision_log.exists() or vision_log.stat().st_size == 0:
                all_failures.append(f"{unit.unit_id}: missing Phase 3.0 vision enrichment log")
            blocks, failures = extract_blocks(unit, slug)
            if not blocks:
                failures.append(f"unit {unit.unit_id} has no block IDs")
            title = title_for_unit(Path(unit.chapter_path), unit.unit_id)
            out_path = source_index_path(wiki, slug, unit)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(render_source_index(slug, unit, blocks, title), encoding="utf-8")
            validation = validate_index(out_path, unit, blocks)
            failures.extend(validation["failures"])
            all_ids.extend(block["block_id"] for block in blocks)
            all_failures.extend(f"{unit.unit_id}: {failure}" for failure in failures)
            unit_reports.append(
                {
                    "unit_id": unit.unit_id,
                    "chapter_file": unit.chapter_path,
                    "source_index": rel(out_path, wiki),
                    "chapter_block_count": len(blocks),
                    "indexed_block_count": validation["indexed_count"],
                    "category_counts": validation["category_counts"],
                    "failures": failures,
                }
            )

        duplicates = sorted(block_id for block_id, count in Counter(all_ids).items() if count > 1)
        if duplicates:
            all_failures.append(f"duplicate block IDs across units: {duplicates[:10]}")
        report = {
            "status": "FAIL" if all_failures else "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "phase_3_0_gate": phase30,
            "unit_count": len(units),
            "total_block_ids": len(all_ids),
            "unique_block_ids": len(set(all_ids)),
            "units": unit_reports,
            "failures": all_failures,
        }
        write_json(report_path, report)
        if all_failures:
            raise RuntimeError("; ".join(all_failures[:10]))

        phase31_gate = write_gate(
            wiki,
            slug,
            "3.1",
            "PASS",
            {
                "report": rel(report_path, wiki),
                "phase_3_0_gate": phase30,
                "unit_count": len(units),
                "total_block_ids": len(all_ids),
                "unique_block_ids": len(set(all_ids)),
            },
        )
        gates["3.1"] = rel(phase31_gate, wiki)
        if "3.1" not in completed:
            completed.append("3.1")
        write_state(wiki, slug, "READY_FOR_3.2", "3.1", completed, gates)
    except Exception as exc:
        if report and report.get("status") != "FAIL":
            report["status"] = "FAIL"
            report["failures"] = [str(exc)]
            write_json(report_path, report)
        fail_gate = write_gate(wiki, slug, "3.1", "FAIL", {"reason": str(exc), "report": rel(report_path, wiki) if report_path.exists() else ""})
        gates["3.1"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.1", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_3_1_gate": gates["3.1"],
                "report": rel(report_path, wiki),
                "unit_count": len(units),
                "total_block_ids": len(all_ids),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
