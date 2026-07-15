#!/usr/bin/env python3
"""Domain Library Phase 2.3 gated block annotation runner."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from domain_library.paths import default_wiki
from domain_library.pipeline.cli import pipeline_parser
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts.block_annotator import annotate_directory, chapter_number_from_name, is_bare_fallback_chunk
from _meta.scripts.extraction_units import discover_units

DEFAULT_WIKI = default_wiki()
ANY_BLOCKLIKE_RE = re.compile(r"\^(?P<id>[A-Za-z0-9][A-Za-z0-9._-]*-ch\d{1,2}-\d+)\b")


from domain_library.pipeline.common import (  # shared plumbing — audit T10
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
from domain_library.pipeline import common as pipeline_common

RUNNER = "library_phase23_blocks.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase22(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "2.2")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 2.2 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 2.2 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "2.2" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 2.2 complete")
    if state.get("status") not in {"READY_FOR_2.3", "READY_FOR_2.4", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 2.3: {state.get('status')}")
    return state, gate_data


def manifest_chapter_paths(raw_root: Path, manifest: dict[str, Any]) -> list[Path]:
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise RuntimeError("manifest has no chapters")
    paths: list[Path] = []
    for idx, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            raise RuntimeError(f"manifest chapter #{idx} is not an object")
        file_value = chapter.get("file")
        if not isinstance(file_value, str) or not file_value:
            raise RuntimeError(f"manifest chapter #{idx} missing file")
        path = Path(file_value)
        if not path.is_absolute():
            path = raw_root / file_value
        paths.append(path)
    return paths


def validate_manifest_files(raw_root: Path, chapters_dir: Path, manifest_path: Path, slug: str) -> tuple[dict[str, Any], list[Path]]:
    if not manifest_path.exists() or manifest_path.stat().st_size == 0:
        raise FileNotFoundError(f"canonical manifest missing: {manifest_path}")
    manifest = read_json(manifest_path)
    paths = manifest_chapter_paths(raw_root, manifest)
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise RuntimeError(f"manifest references missing chapter files: {missing}")
    manifest_set = {p.resolve() for p in paths}
    actual_set = {p.resolve() for p in chapters_dir.glob("*.md") if ".orig." not in p.name}
    extras = sorted(actual_set - manifest_set)
    if extras:
        raise RuntimeError(f"chapters directory has markdown files not in manifest: {[str(p) for p in extras]}")
    for path in paths:
        if is_bare_fallback_chunk(path):
            raise RuntimeError(f"bare fallback chunk is forbidden in canonical Phase 2.3: {path.name}")
    units = discover_units(chapters_dir, slug)
    if len(units) != len(paths):
        raise RuntimeError(f"manifest has {len(paths)} files but extraction_units discovered {len(units)}")
    return manifest, paths


def scan_block_ids(paths: list[Path], slug: str) -> dict[str, Any]:
    valid_re = re.compile(rf"\^(?P<id>{re.escape(slug)}-ch(?P<ch>\d{{2}})-(?P<n>\d{{4,}}))\b")
    wrong: list[dict[str, Any]] = []
    mismatched_chapter: list[dict[str, Any]] = []
    occurrences: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        file_ch = chapter_number_from_name(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            valid_spans = [match.span() for match in valid_re.finditer(line)]
            for match in valid_re.finditer(line):
                block_id = match.group("id")
                occurrences.setdefault(block_id, []).append({"file": str(path), "line": line_no})
                if file_ch is not None and int(match.group("ch")) != file_ch:
                    mismatched_chapter.append({"file": str(path), "line": line_no, "block_id": block_id, "file_chapter": file_ch})
            for match in ANY_BLOCKLIKE_RE.finditer(line):
                if any(start <= match.start() and match.end() <= end for start, end in valid_spans):
                    continue
                wrong.append({"file": str(path), "line": line_no, "block_id": match.group("id")})
    duplicates = [{"block_id": block_id, "occurrences": occ} for block_id, occ in occurrences.items() if len(occ) > 1]
    return {
        "block_ids": occurrences,
        "wrong_block_ids": wrong,
        "mismatched_chapter_ids": mismatched_chapter,
        "duplicate_block_ids": duplicates,
        "unique_block_ids": len(occurrences),
    }


def validate_annotation(paths: list[Path], slug: str, annotator_report: dict[str, Any]) -> dict[str, Any]:
    scan = scan_block_ids(paths, slug)
    if scan["wrong_block_ids"]:
        raise RuntimeError(f"wrong-slug or malformed block IDs found: {scan['wrong_block_ids'][:5]}")
    if scan["mismatched_chapter_ids"]:
        raise RuntimeError(f"block IDs do not match chapter filenames: {scan['mismatched_chapter_ids'][:5]}")
    if scan["duplicate_block_ids"]:
        raise RuntimeError(f"duplicate block IDs found: {scan['duplicate_block_ids'][:5]}")

    by_file = {Path(record["file"]).resolve(): record for record in annotator_report.get("files", [])}
    missing_blocks: list[str] = []
    empty_substantive: list[str] = []
    for path in paths:
        record = by_file.get(path.resolve())
        if not record:
            missing_blocks.append(str(path))
            continue
        if int(record.get("substantive_lines", 0)) == 0:
            empty_substantive.append(str(path))
            continue
        if int(record.get("block_ids", 0)) == 0:
            missing_blocks.append(str(path))
    if missing_blocks:
        raise RuntimeError(f"substantive chapter files missing block IDs: {missing_blocks}")
    if scan["unique_block_ids"] <= 0:
        raise RuntimeError("no block IDs found after annotation")
    return {"scan": scan, "empty_substantive_files": empty_substantive}


def parse_args() -> argparse.Namespace:
    ap = pipeline_parser("Run Domain Library Phase 2.3 hard block-ID gate", default=DEFAULT_WIKI)
    ap.add_argument("--slug", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    manifest_path = raw_root / "manifest.json"
    report_path = raw_root / "block_annotator-report.json"

    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase22 = preflight_phase22(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
        manifest, paths = validate_manifest_files(raw_root, chapters_dir, manifest_path, slug)

        pre_scan = scan_block_ids(paths, slug)
        if pre_scan["wrong_block_ids"]:
            raise RuntimeError(f"wrong-slug or malformed block IDs found before annotation: {pre_scan['wrong_block_ids'][:5]}")
        if pre_scan["mismatched_chapter_ids"]:
            raise RuntimeError(f"block IDs do not match chapter filenames before annotation: {pre_scan['mismatched_chapter_ids'][:5]}")
        if pre_scan["duplicate_block_ids"]:
            raise RuntimeError(f"duplicate block IDs found before annotation: {pre_scan['duplicate_block_ids'][:5]}")

        annotator_report = annotate_directory(chapters_dir, slug, include_fallback=False)
        if annotator_report.get("status") != "PASS":
            raise RuntimeError(str(annotator_report.get("error", "block annotator failed")))
        validation = validate_annotation(paths, slug, annotator_report)
        detailed_report = {
            **annotator_report,
            "manifest": rel(manifest_path, wiki),
            "manifest_unit_count": manifest.get("unit_count", len(paths)),
            "validation": {
                "unique_block_ids": validation["scan"]["unique_block_ids"],
                "wrong_block_ids": validation["scan"]["wrong_block_ids"],
                "mismatched_chapter_ids": validation["scan"]["mismatched_chapter_ids"],
                "duplicate_block_ids": validation["scan"]["duplicate_block_ids"],
                "empty_substantive_files": validation["empty_substantive_files"],
            },
            "generated_at": utc_now(),
        }
        write_json(report_path, detailed_report)
        phase23_gate = write_gate(
            wiki,
            slug,
            "2.3",
            "PASS",
            {
                "chapters_dir": rel(chapters_dir, wiki),
                "manifest": rel(manifest_path, wiki),
                "report": rel(report_path, wiki),
                "phase_2_2_gate": phase22,
                "files": annotator_report["file_count"],
                "total_added": annotator_report["total_added"],
                "total_preserved": annotator_report["total_preserved"],
                "total_block_ids": annotator_report["total_block_ids"],
                "unique_block_ids": validation["scan"]["unique_block_ids"],
            },
        )
        gates["2.3"] = rel(phase23_gate, wiki)
        if "2.3" not in completed:
            completed.append("2.3")
        write_state(wiki, slug, "READY_FOR_2.4", "2.3", completed, gates)
    except Exception as exc:
        fail_gate = write_gate(wiki, slug, "2.3", "FAIL", {"reason": str(exc)})
        gates["2.3"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "2.3", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_2_3_gate": gates["2.3"],
                "report": rel(report_path, wiki),
                "total_block_ids": annotator_report["total_block_ids"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
