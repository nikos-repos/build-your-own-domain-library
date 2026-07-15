#!/usr/bin/env python3
"""Domain Library Phase 3.0 gated vision-enrichment runner.

This runner does not fabricate visual analysis. It creates/validates the
orchestrator-owned per-unit enrichment logs that a human/vision-capable agent
must fill when `VISION_*_NEEDED` markers exist. If no markers exist, it writes
explicit PASS logs with a local image manifest and advances the pipeline.
"""
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

from _meta.scripts.extraction_units import ExtractionUnit, discover_units
from _meta.scripts.verify_image_refs import verify as verify_image_refs

DEFAULT_WIKI = default_wiki()
VISION_MARKER_RE = re.compile(r"\b(?P<marker>VISION_[A-Z0-9_]+_NEEDED)\b")
BLOCK_ID_RE = re.compile(r"\^(?P<block>[A-Za-z0-9][A-Za-z0-9._-]*-ch\d{2}-\d{4,})\b")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\((?P<ref>[^)]+)\)")
SECTION_RE = re.compile(r"^###\s+(?P<id>\S+)\s*$", re.MULTILINE)
KEY_VALUE_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):\s*(?P<value>.*)$")
REMOTE_PREFIXES = ("http://", "https://", "data:")


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

RUNNER = "library_phase30_vision.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase24(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "2.4")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 2.4 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 2.4 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "2.4" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 2.4 complete")
    if state.get("status") not in {"READY_FOR_3.0", "READY_FOR_3.1", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.0: {state.get('status')}")
    return state, gate_data


def strip_ref(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    if " " in raw and not raw.startswith(("/", "./", "../")):
        raw = raw.split()[0]
    return raw


def fs_ref(raw: str) -> str:
    return strip_ref(raw).split("#", 1)[0].split("?", 1)[0]


def local_image_refs(chapter_path: Path) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for line_no, line in enumerate(chapter_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        for match in IMAGE_RE.finditer(line):
            ref = strip_ref(match.group("ref"))
            target = Path(fs_ref(ref)) if Path(fs_ref(ref)).is_absolute() else chapter_path.parent / fs_ref(ref)
            refs.append({"line": line_no, "ref": ref, "resolved": str(target), "exists": target.exists()})
    return refs


def marker_id(unit_id: str, line_no: int, marker: str, ordinal: int) -> str:
    return f"{unit_id}-L{line_no:04d}-{marker}-{ordinal}"


def scan_unit_markers(unit: ExtractionUnit) -> list[dict[str, Any]]:
    path = Path(unit.chapter_path)
    markers: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    ordinal_by_line: dict[tuple[int, str], int] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        block_match = BLOCK_ID_RE.search(line)
        image_match = IMAGE_RE.search(line)
        for match in VISION_MARKER_RE.finditer(line):
            marker = match.group("marker")
            key = (line_no, marker)
            ordinal_by_line[key] = ordinal_by_line.get(key, 0) + 1
            markers.append(
                {
                    "id": marker_id(unit.unit_id, line_no, marker, ordinal_by_line[key]),
                    "unit_id": unit.unit_id,
                    "chapter_file": str(path),
                    "line": line_no,
                    "marker": marker,
                    "block_id": block_match.group("block") if block_match else "",
                    "image_ref": strip_ref(image_match.group("ref")) if image_match else "",
                    "line_text": line.strip(),
                }
            )
    return markers


def output_dir_for(wiki: Path, slug: str, unit: ExtractionUnit) -> Path:
    return wiki / "_meta" / "extractions" / slug / f"team-{unit.unit_id}"


def enrichment_path(wiki: Path, slug: str, unit: ExtractionUnit) -> Path:
    return output_dir_for(wiki, slug, unit) / "orchestrator-vision-enrichment.md"


def render_log(slug: str, unit: ExtractionUnit, markers: list[dict[str, Any]], images: list[dict[str, Any]], *, status: str) -> str:
    lines = [
        f"# Orchestrator Vision Enrichment — {slug} / {unit.unit_id}",
        "",
        f"status: {status}",
        f"slug: {slug}",
        f"unit_id: {unit.unit_id}",
        f"chapter_file: {unit.chapter_path}",
        f"marker_count: {len(markers)}",
        f"local_image_ref_count: {len(images)}",
        f"generated_at: {utc_now()}",
        "",
        "## Local image refs",
    ]
    if images:
        for item in images:
            lines.append(f"- line {item['line']}: `{item['ref']}` -> `{item['resolved']}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Vision markers"])
    if not markers:
        lines.append("- none")
    else:
        for item in markers:
            lines.extend(
                [
                    f"### {item['id']}",
                    "status: unresolved",
                    f"chapter: {item['chapter_file']}",
                    f"line: {item['line']}",
                    f"marker: {item['marker']}",
                    f"block_id: {item['block_id']}",
                    f"image_ref: {item['image_ref']}",
                    "evidence: ",
                    "patch: ",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def parse_marker_sections(text: str) -> dict[str, dict[str, str]]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, dict[str, str]] = {}
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        body = text[start:end]
        fields: dict[str, str] = {}
        for raw in body.splitlines():
            kv = KEY_VALUE_RE.match(raw.strip())
            if kv:
                fields[kv.group("key")] = kv.group("value").strip()
        sections[match.group("id")] = fields
    return sections


def validate_existing_log(path: Path, markers: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    if not path.exists():
        return [f"missing enrichment log: {path}"], {"resolved": 0, "sections": 0}
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = parse_marker_sections(text)
    failures: list[str] = []
    resolved = 0
    for marker in markers:
        fields = sections.get(marker["id"])
        if not fields:
            failures.append(f"missing section for marker {marker['id']}")
            continue
        if fields.get("status", "").lower() != "resolved":
            failures.append(f"marker {marker['id']} status is not resolved")
            continue
        for key in ("chapter", "line", "marker", "block_id", "evidence", "patch"):
            if not fields.get(key):
                failures.append(f"marker {marker['id']} missing {key}")
        if fields.get("marker") != marker["marker"]:
            failures.append(f"marker {marker['id']} marker type mismatch")
        resolved += 1
    return failures, {"resolved": resolved, "sections": len(sections)}


def ensure_log(path: Path, slug: str, unit: ExtractionUnit, markers: list[dict[str, Any]], images: list[dict[str, Any]], *, status: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if markers and path.exists():
        return
    path.write_text(render_log(slug, unit, markers, images, status=status), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    ap = pipeline_parser("Run Domain Library Phase 3.0 hard vision-enrichment gate", default=DEFAULT_WIKI)
    ap.add_argument("--slug", required=True)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    report_path = raw_root / "vision-enrichment-report.json"
    gates: dict[str, str] = {}
    completed: list[str] = []
    report: dict[str, Any] = {}

    try:
        state, phase24 = preflight_phase24(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
        image_check = verify_image_refs(chapters_dir, forbid_remote=True)
        if image_check["missing"] or image_check["remote_refs"]:
            raise RuntimeError(f"Phase 3.0 requires clean local images; image check failed: {image_check}")

        units = discover_units(chapters_dir, slug)
        if not units:
            raise RuntimeError(f"no extraction units discovered in {chapters_dir}")

        unit_reports: list[dict[str, Any]] = []
        all_failures: list[str] = []
        total_markers = 0
        total_resolved = 0
        total_images = 0
        for unit in units:
            markers = scan_unit_markers(unit)
            images = local_image_refs(Path(unit.chapter_path))
            total_markers += len(markers)
            total_images += len(images)
            path = enrichment_path(wiki, slug, unit)
            if not markers:
                ensure_log(path, slug, unit, markers, images, status="pass")
                resolved_meta = {"resolved": 0, "sections": 0}
                failures: list[str] = []
            else:
                ensure_log(path, slug, unit, markers, images, status="pending")
                failures, resolved_meta = validate_existing_log(path, markers)
                total_resolved += resolved_meta["resolved"]
                all_failures.extend(f"{unit.unit_id}: {failure}" for failure in failures)
            unit_reports.append(
                {
                    "unit_id": unit.unit_id,
                    "chapter_file": unit.chapter_path,
                    "output": rel(path, wiki),
                    "marker_count": len(markers),
                    "resolved_markers": resolved_meta["resolved"],
                    "local_image_refs": len(images),
                    "markers": markers,
                    "failures": failures,
                }
            )

        report = {
            "status": "FAIL" if all_failures else "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "phase_2_4_gate": phase24,
            "unit_count": len(units),
            "marker_count": total_markers,
            "resolved_markers": total_resolved,
            "local_image_refs": total_images,
            "image_check": image_check,
            "units": unit_reports,
            "failures": all_failures,
        }
        write_json(report_path, report)
        if all_failures:
            raise RuntimeError("; ".join(all_failures[:10]))

        phase30_gate = write_gate(
            wiki,
            slug,
            "3.0",
            "PASS",
            {
                "report": rel(report_path, wiki),
                "phase_2_4_gate": phase24,
                "unit_count": len(units),
                "marker_count": total_markers,
                "resolved_markers": total_resolved,
                "local_image_refs": total_images,
            },
        )
        gates["3.0"] = rel(phase30_gate, wiki)
        if "3.0" not in completed:
            completed.append("3.0")
        write_state(wiki, slug, "READY_FOR_3.1", "3.0", completed, gates)
    except Exception as exc:
        if report and report.get("status") != "FAIL":
            report["status"] = "FAIL"
            report["failures"] = [str(exc)]
            write_json(report_path, report)
        fail_gate = write_gate(wiki, slug, "3.0", "FAIL", {"reason": str(exc), "report": rel(report_path, wiki) if report_path.exists() else ""})
        gates["3.0"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.0", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_3_0_gate": gates["3.0"],
                "report": rel(report_path, wiki),
                "marker_count": total_markers,
                "resolved_markers": total_resolved,
                "unit_count": len(units),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
