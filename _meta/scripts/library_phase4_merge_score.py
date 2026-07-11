#!/usr/bin/env python3
"""Domain Library Phase 4 merge, score, filter, validate, and confirm gate.

Phase 4 has a real user-confirmation boundary. `--prepare` creates the scored
candidate list and leaves the pipeline awaiting confirmation. `--confirm` records
the human-selected concept slugs, writes the PASS gate, and advances to Phase 5.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import blockid_validator
import latex_slug_filter
import scoring_layer

DEFAULT_WIKI = SCRIPT_DIR.parents[1]
RUNNER = "library_phase4_merge_score.py"

# Lane order comes from _meta/config/domain.json lane order; populated below after imports.
LANE_ORDER: list[str] = []
EXTRACTION_SKIP_NAMES = {
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


from pipeline_common import (  # shared plumbing — audit T10
    confirmation_path,
    confirmed_path,
    extraction_root,
    gate_path,
    load_state,
    read_json,
    rel,
    resolve_path,
    schema_dir,
    state_path,
    utc_now,
    write_gate,
    write_json,
)
import pipeline_common


def _load_lane_order(wiki: Path) -> None:
    LANE_ORDER[:] = list(pipeline_common.configured_lanes(wiki))


_load_lane_order(DEFAULT_WIKI)


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def chapters_dir(wiki: Path, slug: str) -> Path:
    return wiki / "raw" / "papers" / slug / "chapters"


def scored_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "master-scored.json"


def top_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "master-top.json"


def clean_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "master-top-clean.json"


def scoring_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "phase4-scoring-report.json"


def candidates_json_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "concept-selection-candidates.json"


def candidates_md_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "concept-selection-candidates.md"


def rationale_json_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "concept-selection-rationale-packet.json"


def rationale_md_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "concept-selection-rationale-packet.md"


def blockid_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "blockid-validation-report.json"


def blockid_marker_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "_blockid_valid"


def preflight_phase35(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.5")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.5 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.5 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.5" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.5 complete")
    if state.get("status") not in {"READY_FOR_4", "IN_PROGRESS", "AWAITING_USER_CONFIRMATION"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 4: {state.get('status')}")
    report_ref = gate_data.get("presentation_report")
    if report_ref:
        report = resolve_path(report_ref, wiki)
        if not report.exists():
            raise FileNotFoundError(f"Phase 3.5 presentation report not found: {report}")
        data = read_json(report)
        if data.get("status") != "PASS":
            raise RuntimeError(f"Phase 3.5 presentation report is not PASS: {report}")
    return state, gate_data


def require_phase34_schema_pass(wiki: Path, slug: str) -> None:
    root = extraction_root(wiki, slug)
    marker = root / "_validation_passed"
    report = root / "schema-validation-report.json"
    if not marker.exists():
        raise FileNotFoundError(f"Phase 3.4 validation marker missing: {marker}")
    if "validated_by: library_phase34_verify.py" not in marker.read_text(encoding="utf-8", errors="replace"):
        raise RuntimeError("_validation_passed was not machine-written by library_phase34_verify.py")
    data = read_json(report)
    if data.get("status") != "PASS" or data.get("valid") != data.get("total") or int(data.get("total", 0)) <= 0:
        raise RuntimeError(f"schema-validation-report.json is not a non-empty PASS: {report}")


def validate_extraction_sources(extractions: list[dict[str, Any]], slug: str) -> None:
    for idx, item in enumerate(extractions):
        if item.get("source") != slug:
            raise RuntimeError(f"extraction {idx} source mismatch: {item.get('source')} != {slug}")
        if not isinstance(item.get("concepts"), list) or not item["concepts"]:
            raise RuntimeError(f"extraction {idx} has no concepts")


def write_blockid_marker(path: Path, slug: str, report: dict[str, Any]) -> None:
    path.write_text(
        "\n".join(
            [
                "status: PASS",
                f"slug: {slug}",
                f"validated_by: blockid_validator.py",
                f"chapter_block_ids: {report['chapter_block_ids']}",
                f"referenced_block_ids: {report['referenced_block_ids']}",
                f"missing_count: {report['missing_count']}",
                f"generated_at: {utc_now()}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def clean_concepts_from_data(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    concepts = data.get("concepts", {})
    if isinstance(concepts, dict):
        return {str(k): v for k, v in concepts.items() if isinstance(v, dict)}
    if isinstance(concepts, list):
        return {str(c.get("slug")): c for c in concepts if isinstance(c, dict) and c.get("slug")}
    raise RuntimeError("clean concept file has invalid concepts shape")


def lane_sort_key(lane: str) -> tuple[int, str]:
    try:
        return (LANE_ORDER.index(lane), lane)
    except ValueError:
        return (len(LANE_ORDER), lane)


def lane_from_schema_file(path: Path) -> str:
    stem = path.stem
    for lane in LANE_ORDER:
        if stem.endswith(f"-{lane}"):
            return lane
    return stem.rsplit("-", 1)[-1]


def concept_source_map(sdir: Path) -> dict[str, list[dict[str, Any]]]:
    sources: dict[str, list[dict[str, Any]]] = {}
    for json_file in sorted(sdir.glob("*.json")):
        if json_file.name.startswith("_") or json_file.name in EXTRACTION_SKIP_NAMES or json_file.name.endswith("-report.json"):
            continue
        data = read_json(json_file)
        lane = lane_from_schema_file(json_file)
        chapter = data.get("chapter")
        chapter_title = str(data.get("chapter_title", ""))
        for concept in data.get("concepts", []):
            if not isinstance(concept, dict) or not concept.get("slug"):
                continue
            block_ids = [str(block_id) for block_id in concept.get("block_ids", []) if block_id]
            sources.setdefault(str(concept["slug"]), []).append(
                {
                    "lane": lane,
                    "file": json_file.name,
                    "chapter": chapter,
                    "chapter_title": chapter_title,
                    "block_ids": sorted(set(block_ids)),
                }
            )
    return sources


def source_index_blocks(wiki: Path, slug: str) -> dict[str, dict[str, Any]]:
    blocks: dict[str, dict[str, Any]] = {}
    for index_path in sorted(extraction_root(wiki, slug).glob("team-*/orchestrator-source-index.md")):
        text = index_path.read_text(encoding="utf-8")
        marker = "<!-- source_index_json"
        start = text.find(marker)
        if start < 0:
            continue
        payload_text = text[start + len(marker):].rsplit("-->", 1)[0].strip()
        payload = json.loads(payload_text)
        unit_id = index_path.parent.name.removeprefix("team-")
        for block in payload.get("blocks", []):
            if not isinstance(block, dict) or not block.get("block_id"):
                continue
            row = dict(block)
            row["unit_id"] = unit_id
            blocks[str(block["block_id"])] = row
    return blocks


def duplicate_risks_for(slug: str, duplicate_flags: list[dict[str, Any]] | None, aliases: list[str]) -> list[str]:
    risks: list[str] = []
    alias_set = {slug, *aliases}
    for flag in duplicate_flags or []:
        flag_slugs = {str(item) for item in flag.get("slugs", [])}
        if not alias_set & flag_slugs:
            continue
        if flag.get("kind") == "in-batch":
            risks.append(f"in-batch {' / '.join(sorted(flag_slugs))}: {flag.get('reason')}")
        else:
            existing = ", ".join(str(item) for item in flag.get("existing", []))
            risks.append(f"vs existing {existing}: {flag.get('reason')}")
    if aliases and aliases != [slug]:
        risks.append(f"merged aliases: {', '.join(aliases)}")
    return risks


def strongest_blocks(block_ids: list[str], source_rows: list[dict[str, Any]], limit: int = 5) -> list[str]:
    counts: dict[str, int] = {}
    for row in source_rows:
        for block_id in row.get("block_ids", []):
            counts[str(block_id)] = counts.get(str(block_id), 0) + 1
    for block_id in block_ids:
        counts.setdefault(str(block_id), 1)
    return [block_id for block_id, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def source_section_diversity(block_ids: list[str], index_blocks: dict[str, dict[str, Any]]) -> list[str]:
    categories = {
        str(index_blocks[block_id].get("category"))
        for block_id in block_ids
        if block_id in index_blocks and index_blocks[block_id].get("category")
    }
    return sorted(categories)


def build_rationale_packet(
    wiki: Path,
    slug: str,
    sdir: Path,
    clean_concepts: dict[str, dict[str, Any]],
    all_scored: list[dict[str, Any]],
    removed: list[str],
    duplicate_flags: list[dict[str, Any]] | None,
    min_score: int,
    top_n: int | None,
) -> dict[str, Any]:
    source_map = concept_source_map(sdir)
    index_blocks = source_index_blocks(wiki, slug)
    clean_slugs = set(clean_concepts)
    removed_slugs = set(removed)
    rationales: list[dict[str, Any]] = []
    for rank, concept in enumerate(all_scored, start=1):
        concept_slug = str(concept.get("slug"))
        aliases = [str(item) for item in concept.get("merged_slugs", [concept_slug])]
        source_rows = [row for alias in aliases for row in source_map.get(alias, [])]
        supporting_lanes = sorted({str(row["lane"]) for row in source_rows}, key=lane_sort_key)
        block_ids = [str(block_id) for block_id in concept.get("block_ids", []) if block_id]
        candidate_status = "included" if concept_slug in clean_slugs else "excluded"
        if concept_slug in clean_slugs:
            reason = f"Include for human review: score {concept.get('score')} >= min_score {min_score} and survived LaTeX/artifact filtering."
        elif concept_slug in removed_slugs:
            reason = "Exclude from clean candidates: removed by LaTeX/artifact slug filter; visible here for audit."
        elif top_n is not None and rank > top_n:
            reason = f"Exclude from clean candidates: outside top_n {top_n}; visible here for audit."
        else:
            reason = f"Exclude from clean candidates: score {concept.get('score')} below min_score {min_score}; visible here for audit."
        rationales.append(
            {
                "rank": rank,
                "slug": concept_slug,
                "name": concept.get("name", concept_slug),
                "status": candidate_status,
                "score": concept.get("score"),
                "confidence": concept.get("confidence"),
                "supporting_lanes": supporting_lanes,
                "source_files": sorted({str(row["file"]) for row in source_rows}),
                "strongest_block_ids": strongest_blocks(block_ids, source_rows),
                "source_section_diversity": source_section_diversity(block_ids, index_blocks),
                "duplicate_alias_risks": duplicate_risks_for(concept_slug, duplicate_flags, aliases),
                "reason": reason,
            }
        )
    return {
        "schema_version": 1,
        "status": "AWAITING_USER_CONFIRMATION",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "lesson_candidate": "L-010",
        "min_score": min_score,
        "top_n": top_n,
        "clean_candidate_count": len(clean_concepts),
        "total_scored_concepts": len(all_scored),
        "rationale_count": len(rationales),
        "rationales": rationales,
    }


def markdown_cell(value: Any) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item) for item in value) if value else "none"
    else:
        text = str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_rationale_markdown(packet: dict[str, Any]) -> str:
    lines = [
        f"# Phase 4 Candidate Rationale Packet — {packet['slug']}",
        "",
        "status: awaiting_user_confirmation",
        "lesson_candidate: L-010",
        f"clean_candidate_count: {packet['clean_candidate_count']}",
        f"total_scored_concepts: {packet['total_scored_concepts']}",
        "",
        "This packet does not confirm, discard, or overwrite any selection. It keeps every scored concept visible for the human reviewer's Phase 4 review.",
        "",
        "| Rank | Status | Slug | Score | Supporting lanes | Strongest block IDs | Source sections | Duplicate / alias risks | Reason |",
        "|---:|---|---|---:|---|---|---|---|---|",
    ]
    for row in packet["rationales"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(row["rank"]),
                    markdown_cell(row["status"]),
                    f"`{markdown_cell(row['slug'])}`",
                    markdown_cell(row["score"]),
                    markdown_cell(row["supporting_lanes"]),
                    markdown_cell(row["strongest_block_ids"]),
                    markdown_cell(row["source_section_diversity"]),
                    markdown_cell(row["duplicate_alias_risks"]),
                    markdown_cell(row["reason"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_candidates_markdown(slug: str, clean_concepts: dict[str, dict[str, Any]], all_scored: list[dict[str, Any]], removed: list[str], min_score: int, duplicate_flags: list[dict[str, Any]] | None = None) -> str:
    lines = [
        f"# Phase 4 Concept Selection Candidates — {slug}",
        "",
        "status: awaiting_user_confirmation",
        f"min_score: {min_score}",
        f"candidate_count: {len(clean_concepts)}",
        f"total_scored_concepts: {len(all_scored)}",
        "",
    ]
    if duplicate_flags:
        lines.extend(
            [
                "## Possible duplicates — resolve before confirming",
                "",
                "Selecting both slugs of an in-batch pair, or a slug flagged against an",
                "existing page, is refused unless `--allow-flagged-duplicates` is passed.",
                "",
            ]
        )
        for f in duplicate_flags:
            if f.get("kind") == "in-batch":
                lines.append(f"- in-batch: {' vs '.join(f'`{s}`' for s in f['slugs'])} — {f['reason']}")
            else:
                lines.append(f"- vs-existing: `{f['slugs'][0]}` vs existing page(s) {', '.join(f'`{e}`' for e in f['existing'])} — {f['reason']}")
        lines.append("")
    lines.extend([
        "## User action required",
        "",
        "Review the sorted candidates below and the linked rationale packet. Write `_meta/extractions/<slug>/phase4-user-selection.json` with:",
        "",
        "```json",
        '{"confirmed_slugs": ["candidate-slug"]}',
        "```",
        "",
        "Then run:",
        "",
        "```bash",
        f"python3 _meta/scripts/{RUNNER} --slug {slug} --confirm --selection _meta/extractions/{slug}/phase4-user-selection.json",
        "```",
        "",
        "## Rationale packet",
        "",
        f"- JSON: `{rationale_json_path(Path('.'), slug).name}`",
        f"- Markdown: `{rationale_md_path(Path('.'), slug).name}`",
        "",
        "## Clean candidates",
        "",
        "| Rank | Slug | Score | Chapters | Confidence | Blocks |",
        "|---:|---|---:|---:|---:|---:|",
    ])
    for rank, (concept_slug, concept) in enumerate(sorted(clean_concepts.items(), key=lambda kv: (-int(kv[1].get("score", 0)), kv[0])), start=1):
        lines.append(
            f"| {rank} | `{concept_slug}` | {concept.get('score', 0)} | {len(concept.get('chapters', []))} | {float(concept.get('confidence', 0.0)):.2f} | {len(concept.get('block_ids', []))} |"
        )
    lines.extend(["", "## LaTeX/artifact slugs removed", ""])
    if removed:
        lines.extend(f"- `{item}`" for item in removed)
    else:
        lines.append("- none")
    lines.extend(["", "## All scored concepts", ""])
    for concept in all_scored:
        lines.append(f"- `{concept.get('slug')}` — score {concept.get('score')} — blocks {len(concept.get('block_ids', []))}")
    return "\n".join(lines).rstrip() + "\n"


def prepare(args: argparse.Namespace) -> None:
    wiki = Path(args.wiki).resolve()
    _load_lane_order(wiki)
    slug = pipeline_common.validate_slug(args.slug)
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase35_gate = preflight_phase35(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        require_phase34_schema_pass(wiki, slug)
        sdir = schema_dir(wiki, slug)
        cdir = chapters_dir(wiki, slug)
        if not sdir.exists():
            raise FileNotFoundError(f"schema directory not found: {sdir}")
        if not cdir.exists():
            raise FileNotFoundError(f"chapters directory not found: {cdir}")

        extractions = scoring_layer.load_extractions(sdir)
        validate_extraction_sources(extractions, slug)
        merged = scoring_layer.merge_concepts(extractions)
        scored = scoring_layer.score_all(merged)
        if not scored:
            raise RuntimeError("scoring produced no concepts")
        write_json(scored_path(wiki, slug), {"slug": slug, "total_concepts": len(scored), "concepts": scored})

        selected = scoring_layer.threshold(scored, args.min_score, args.top_n)
        if not selected:
            raise RuntimeError(f"threshold selected zero concepts from {len(scored)} scored concepts")
        write_json(
            top_path(wiki, slug),
            {
                "slug": slug,
                "threshold": args.min_score,
                "top_n": args.top_n,
                "total_concepts": len(scored),
                "selected_concepts": len(selected),
                "concepts": {c["slug"]: c for c in selected},
            },
        )
        clean_data = latex_slug_filter.filter_slugs(top_path(wiki, slug), clean_path(wiki, slug))
        clean_concepts = clean_concepts_from_data(clean_data)
        removed = list(clean_data.get("_latex_filtered", {}).get("removed_slugs", []))
        if not clean_concepts:
            raise RuntimeError("LaTeX filtering removed every selected concept")

        existing_pages = sorted(p.stem for p in (wiki / "concepts").glob("*.md"))
        duplicate_flags = scoring_layer.near_duplicate_groups(sorted(clean_concepts), existing_pages)

        bid_report = blockid_validator.validate(slug, cdir, sdir)
        write_json(blockid_report_path(wiki, slug), bid_report)
        if not bid_report.get("valid") or int(bid_report.get("referenced_block_ids", 0)) <= 0:
            raise RuntimeError("block-ID validation failed or referenced zero block IDs")
        write_blockid_marker(blockid_marker_path(wiki, slug), slug, bid_report)

        rationale_packet = build_rationale_packet(
            wiki,
            slug,
            sdir,
            clean_concepts,
            scored,
            removed,
            duplicate_flags,
            args.min_score,
            args.top_n,
        )
        write_json(rationale_json_path(wiki, slug), rationale_packet)
        rationale_md_path(wiki, slug).write_text(render_rationale_markdown(rationale_packet), encoding="utf-8")

        candidates = {
            "schema_version": 1,
            "status": "AWAITING_USER_CONFIRMATION",
            "slug": slug,
            "generated_at": utc_now(),
            "generated_by": RUNNER,
            "min_score": args.min_score,
            "top_n": args.top_n,
            "total_scored_concepts": len(scored),
            "selected_before_latex_filter": len(selected),
            "candidate_count": len(clean_concepts),
            "removed_latex_slugs": removed,
            "duplicate_flags": duplicate_flags,
            "candidates": clean_concepts,
            "rationale_packet_json": rel(rationale_json_path(wiki, slug), wiki),
            "rationale_packet_markdown": rel(rationale_md_path(wiki, slug), wiki),
        }
        write_json(candidates_json_path(wiki, slug), candidates)
        candidates_md_path(wiki, slug).write_text(
            render_candidates_markdown(slug, clean_concepts, scored, removed, args.min_score, duplicate_flags), encoding="utf-8"
        )

        report = {
            "schema_version": 1,
            "status": "AWAITING_USER_CONFIRMATION",
            "slug": slug,
            "generated_at": utc_now(),
            "generated_by": RUNNER,
            "phase_3_5_gate": phase35_gate,
            "schema_dir": rel(sdir, wiki),
            "master_scored": rel(scored_path(wiki, slug), wiki),
            "master_top": rel(top_path(wiki, slug), wiki),
            "master_top_clean": rel(clean_path(wiki, slug), wiki),
            "candidate_json": rel(candidates_json_path(wiki, slug), wiki),
            "candidate_markdown": rel(candidates_md_path(wiki, slug), wiki),
            "rationale_packet_json": rel(rationale_json_path(wiki, slug), wiki),
            "rationale_packet_markdown": rel(rationale_md_path(wiki, slug), wiki),
            "blockid_report": rel(blockid_report_path(wiki, slug), wiki),
            "blockid_marker": rel(blockid_marker_path(wiki, slug), wiki),
            "total_extraction_files": len(extractions),
            "total_scored_concepts": len(scored),
            "selected_before_latex_filter": len(selected),
            "candidate_count": len(clean_concepts),
            "removed_latex_slugs": removed,
            "failures": [],
        }
        write_json(scoring_report_path(wiki, slug), report)
        phase4_gate = write_gate(
            wiki,
            slug,
            "4",
            "AWAITING_USER_CONFIRMATION",
            {
                "scoring_report": rel(scoring_report_path(wiki, slug), wiki),
                "candidate_markdown": rel(candidates_md_path(wiki, slug), wiki),
                "candidate_json": rel(candidates_json_path(wiki, slug), wiki),
                "rationale_packet_json": rel(rationale_json_path(wiki, slug), wiki),
                "rationale_packet_markdown": rel(rationale_md_path(wiki, slug), wiki),
                "candidate_count": len(clean_concepts),
                "blockid_report": rel(blockid_report_path(wiki, slug), wiki),
            },
        )
        gates["4"] = rel(phase4_gate, wiki)
        write_state(wiki, slug, "AWAITING_USER_CONFIRMATION", "4", completed, gates)
    except Exception as exc:
        if not gates:
            try:
                state = load_state(wiki, slug)
                gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
                completed = [str(x) for x in state.get("completed_phases", [])]
            except Exception:
                pass
        fail_gate = write_gate(wiki, slug, "4", "FAIL", {"reason": str(exc), "stage": "prepare", "scoring_report": rel(scoring_report_path(wiki, slug), wiki)})
        gates["4"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "4", completed, gates)
        if not scoring_report_path(wiki, slug).exists():
            write_json(
                scoring_report_path(wiki, slug),
                {
                    "schema_version": 1,
                    "status": "FAIL",
                    "slug": slug,
                    "generated_at": utc_now(),
                    "generated_by": RUNNER,
                    "stage": "prepare",
                    "failures": [str(exc)],
                },
            )
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "AWAITING_USER_CONFIRMATION",
                "slug": slug,
                "phase_4_gate": gates["4"],
                "candidate_markdown": rel(candidates_md_path(wiki, slug), wiki),
                "candidate_count": len(clean_concepts),
            },
            indent=2,
        )
    )


class SelectionError(RuntimeError):
    """Invalid user selection: recoverable — fix the selection JSON and rerun
    --confirm. Does not mark the pipeline FAILED."""


def selection_slugs(selection: dict[str, Any]) -> list[str]:
    for key in ("confirmed_slugs", "selected_slugs", "slugs"):
        value = selection.get(key)
        if isinstance(value, list):
            return [str(item) for item in value]
    concepts = selection.get("concepts")
    if isinstance(concepts, dict):
        return [str(key) for key in concepts]
    if isinstance(concepts, list):
        out = []
        for item in concepts:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict) and item.get("slug"):
                out.append(str(item["slug"]))
        return out
    raise RuntimeError("selection JSON must contain confirmed_slugs, selected_slugs, slugs, or concepts")


def confirm(args: argparse.Namespace) -> None:
    wiki = Path(args.wiki).resolve()
    _load_lane_order(wiki)
    slug = pipeline_common.validate_slug(args.slug)
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase35_gate = preflight_phase35(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if state.get("status") != "AWAITING_USER_CONFIRMATION":
            raise RuntimeError(f"Phase 4 confirmation requires AWAITING_USER_CONFIRMATION state, got {state.get('status')}")
        scoring_report = read_json(scoring_report_path(wiki, slug))
        if scoring_report.get("status") != "AWAITING_USER_CONFIRMATION":
            raise RuntimeError("Phase 4 scoring report is not awaiting user confirmation")
        candidates = read_json(candidates_json_path(wiki, slug))
        clean_concepts = clean_concepts_from_data({"concepts": candidates.get("candidates", {})})
        if not clean_concepts:
            raise RuntimeError("no clean concepts available for confirmation")
        selection_file = resolve_path(args.selection, wiki)
        selection = read_json(selection_file)
        slugs = selection_slugs(selection)
        if not slugs:
            raise SelectionError("confirmation selected zero concepts")
        duplicates = sorted(slug_value for slug_value, count in {s: slugs.count(s) for s in slugs}.items() if count > 1)
        if duplicates:
            raise SelectionError(f"duplicate selected slugs: {duplicates}")
        unknown = sorted(set(slugs) - set(clean_concepts))
        if unknown:
            raise SelectionError(f"selected slugs are not clean Phase 4 candidates: {unknown}")
        dirty = sorted(slug_value for slug_value in slugs if not latex_slug_filter.is_clean_slug(slug_value))
        if dirty:
            raise SelectionError(f"selected slugs failed LaTeX/artifact filter: {dirty}")
        if not args.allow_flagged_duplicates:
            selected_set = set(slugs)
            flags = candidates.get("duplicate_flags", [])
            both_selected = [f for f in flags if f.get("kind") == "in-batch" and len(selected_set & set(f.get("slugs", []))) > 1]
            vs_existing = [f for f in flags if f.get("kind") == "vs-existing" and selected_set & set(f.get("slugs", []))]
            if both_selected or vs_existing:
                details = [f"{'+'.join(f['slugs'])} ({f['reason']})" for f in both_selected]
                details += [f"{f['slugs'][0]} vs existing {','.join(f['existing'])} ({f['reason']})" for f in vs_existing]
                raise SelectionError(
                    "selection includes duplicate-flagged slugs — pick one per flagged group, or rerun with "
                    f"--allow-flagged-duplicates for an intentional override: {details}"
                )

        selected_concepts = {slug_value: clean_concepts[slug_value] for slug_value in slugs}
        confirmed = {
            "schema_version": 1,
            "status": "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "generated_by": RUNNER,
            "selection_file": rel(selection_file, wiki),
            "phase_3_5_gate": phase35_gate,
            "scoring_report": rel(scoring_report_path(wiki, slug), wiki),
            "candidate_json": rel(candidates_json_path(wiki, slug), wiki),
            "selected_count": len(selected_concepts),
            "selected_slugs": slugs,
            "concepts": selected_concepts,
        }
        write_json(confirmation_path(wiki, slug), confirmed)
        write_json(
            confirmed_path(wiki, slug),
            {
                "schema_version": 1,
                "status": "PASS",
                "slug": slug,
                "generated_at": utc_now(),
                "selected_concepts": len(selected_concepts),
                "concepts": selected_concepts,
            },
        )
        scoring_report["status"] = "PASS"
        scoring_report["confirmation"] = rel(confirmation_path(wiki, slug), wiki)
        scoring_report["master_confirmed"] = rel(confirmed_path(wiki, slug), wiki)
        scoring_report["selected_count"] = len(selected_concepts)
        write_json(scoring_report_path(wiki, slug), scoring_report)
        phase4_gate = write_gate(
            wiki,
            slug,
            "4",
            "PASS",
            {
                "scoring_report": rel(scoring_report_path(wiki, slug), wiki),
                "confirmation": rel(confirmation_path(wiki, slug), wiki),
                "master_confirmed": rel(confirmed_path(wiki, slug), wiki),
                "selected_count": len(selected_concepts),
                "blockid_report": rel(blockid_report_path(wiki, slug), wiki),
                "blockid_marker": rel(blockid_marker_path(wiki, slug), wiki),
            },
        )
        gates["4"] = rel(phase4_gate, wiki)
        if "4" not in completed:
            completed.append("4")
        write_state(wiki, slug, "READY_FOR_5", "4", completed, gates)
    except Exception as exc:
        if not gates:
            try:
                state = load_state(wiki, slug)
                gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
                completed = [str(x) for x in state.get("completed_phases", [])]
            except Exception:
                pass
        fail_gate = write_gate(wiki, slug, "4", "FAIL", {"reason": str(exc), "stage": "confirm", "scoring_report": rel(scoring_report_path(wiki, slug), wiki)})
        gates["4"] = rel(fail_gate, wiki)
        if isinstance(exc, SelectionError):
            # Recoverable: the candidate list is still valid — fix the
            # selection JSON and rerun --confirm. The FAIL gate above still
            # blocks Phase 5 until a confirmation passes.
            write_state(wiki, slug, "AWAITING_USER_CONFIRMATION", "4", completed, gates)
        else:
            write_state(wiki, slug, "FAILED", "4", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_4_gate": gates["4"],
                "confirmation": rel(confirmation_path(wiki, slug), wiki),
                "master_confirmed": rel(confirmed_path(wiki, slug), wiki),
                "selected_count": len(selected_concepts),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 4 merge/score/filter/block-ID/user-confirmation gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Merge, score, filter, validate, and await user confirmation")
    mode.add_argument("--confirm", action="store_true", help="Record user-selected concept slugs and write PASS gate")
    ap.add_argument("--selection", help="Selection JSON path for --confirm")
    ap.add_argument("--min-score", type=int, default=9)
    ap.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Optional hard cap on candidates. Default: no cap — --min-score governs selection, since book sizes vary (the old fixed 56 was arbitrary).",
    )
    ap.add_argument("--allow-flagged-duplicates", action="store_true", help="Confirm a selection despite duplicate flags (intentional override)")
    args = ap.parse_args()
    if not args.prepare and not args.confirm:
        args.prepare = True
    if args.confirm and not args.selection:
        ap.error("--confirm requires --selection")
    if args.min_score < 0:
        ap.error("--min-score must be non-negative")
    if args.top_n is not None and args.top_n <= 0:
        ap.error("--top-n must be positive")
    return args


def main() -> None:
    args = parse_args()
    if args.confirm:
        confirm(args)
    else:
        prepare(args)


if __name__ == "__main__":
    main()
