#!/usr/bin/env python3
"""Domain Library Phase 3.2 gated size-split runner.

Phase 3.2 runs after Phase 3.1 and before specialist dispatch. If a unit is
oversized, the runner splits it with zero overlap, rediscoveres units, archives
superseded team directories, regenerates orchestrator vision/source-index
artifacts for the current unit set, writes a hard gate, and advances the durable
pipeline state to READY_FOR_3.3.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from domain_library.paths import default_wiki
from domain_library.pipeline.cli import pipeline_parser
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts import library_phase30_vision as phase30
from _meta.scripts import library_phase31_source_index as phase31
from _meta.scripts.chapter_size_splitter import line_count, split_chapter
from _meta.scripts.extraction_units import ExtractionUnit, discover_units
from _meta.scripts.verify_image_refs import verify as verify_image_refs

DEFAULT_WIKI = default_wiki()
RUNNER = "library_phase32_size_split.py"


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


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase31(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.1")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.1 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.1 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.1" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.1 complete")
    if state.get("status") not in {"READY_FOR_3.2", "READY_FOR_3.3", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.2: {state.get('status')}")
    return state, gate_data


def active_markdown_files(chapters_dir: Path) -> list[Path]:
    return sorted(path for path in chapters_dir.glob("*.md") if ".orig." not in path.name)


def discover_current_units(chapters_dir: Path, slug: str) -> list[ExtractionUnit]:
    units = discover_units(chapters_dir, slug)
    if not units:
        raise RuntimeError(f"no extraction units discovered in {chapters_dir}")
    discovered = {unit.filename for unit in units}
    unmapped = [path.name for path in active_markdown_files(chapters_dir) if path.name not in discovered]
    if unmapped:
        raise RuntimeError(f"chapter markdown files do not map to extraction units: {unmapped}")
    return units


def validate_prerequisites(wiki: Path, slug: str, units: list[ExtractionUnit]) -> list[str]:
    failures: list[str] = []
    for unit in units:
        vision = phase30.enrichment_path(wiki, slug, unit)
        source = phase31.source_index_path(wiki, slug, unit)
        if not vision.exists() or vision.stat().st_size == 0:
            failures.append(f"{unit.unit_id}: missing non-empty orchestrator-vision-enrichment.md")
        if not source.exists() or source.stat().st_size == 0:
            failures.append(f"{unit.unit_id}: missing non-empty orchestrator-source-index.md")
    return failures


def oversized_units(units: list[ExtractionUnit], max_lines: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        path = Path(unit.chapter_path)
        count = line_count(path)
        if count > max_lines:
            rows.append({"unit": unit, "path": path, "lines": count})
    return rows


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 1000):
        candidate = path.with_name(f"{path.name}.{idx}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find archive destination for {path}")


def archive_superseded_team_dirs(wiki: Path, slug: str, units: list[ExtractionUnit]) -> list[dict[str, str]]:
    archived: list[dict[str, str]] = []
    root = extraction_root(wiki, slug)
    archive_root = root / "_superseded" / "phase-3.2"
    for unit in units:
        src = root / f"team-{unit.unit_id}"
        if not src.exists():
            continue
        dest = unique_destination(archive_root / src.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        archived.append({"unit_id": unit.unit_id, "from": rel(src, wiki), "to": rel(dest, wiki)})
    return archived


def marker_fields_by_key(log_path: Path) -> dict[tuple[str, str], deque[dict[str, str]]]:
    text = log_path.read_text(encoding="utf-8", errors="replace")
    sections = phase30.parse_marker_sections(text)
    keyed: dict[tuple[str, str], deque[dict[str, str]]] = defaultdict(deque)
    for fields in sections.values():
        marker = fields.get("marker", "")
        block_id = fields.get("block_id", "")
        if marker and block_id:
            keyed[(marker, block_id)].append(fields)
    return keyed


def render_inherited_vision_log(
    wiki: Path,
    slug: str,
    unit: ExtractionUnit,
    markers: list[dict[str, Any]],
    images: list[dict[str, Any]],
    inherited_from_unit: str,
    inherited_from_log: Path,
    inherited_fields: dict[tuple[str, str], deque[dict[str, str]]],
) -> tuple[str, list[str], int]:
    failures: list[str] = []
    resolved = 0
    lines = [
        f"# Orchestrator Vision Enrichment — {slug} / {unit.unit_id}",
        "",
        "status: pass",
        f"slug: {slug}",
        f"unit_id: {unit.unit_id}",
        f"chapter_file: {unit.chapter_path}",
        f"marker_count: {len(markers)}",
        f"local_image_ref_count: {len(images)}",
        f"inherited_from_unit: {inherited_from_unit}",
        f"inherited_from_log: {rel(inherited_from_log, wiki)}",
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
        return "\n".join(lines).rstrip() + "\n", failures, resolved

    for marker in markers:
        key = (str(marker["marker"]), str(marker["block_id"]))
        queue = inherited_fields.get(key)
        fields = queue.popleft() if queue else None
        if not fields:
            failures.append(f"{unit.unit_id}: no inherited resolved marker evidence for {key}")
            evidence = ""
            patch = ""
        elif fields.get("status", "").lower() != "resolved":
            failures.append(f"{unit.unit_id}: inherited marker evidence is not resolved for {key}")
            evidence = fields.get("evidence", "")
            patch = fields.get("patch", "")
        else:
            evidence = fields.get("evidence", "")
            patch = fields.get("patch", "")
            if not evidence or not patch:
                failures.append(f"{unit.unit_id}: inherited marker evidence missing evidence/patch for {key}")
            resolved += 1
        lines.extend(
            [
                f"### {marker['id']}",
                "status: resolved" if fields and fields.get("status", "").lower() == "resolved" else "status: unresolved",
                f"chapter: {marker['chapter_file']}",
                f"line: {marker['line']}",
                f"marker: {marker['marker']}",
                f"block_id: {marker['block_id']}",
                f"image_ref: {marker['image_ref']}",
                f"evidence: {evidence}",
                f"patch: {patch}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n", failures, resolved


def regenerate_vision_logs(
    wiki: Path,
    slug: str,
    chapters_dir: Path,
    units: list[ExtractionUnit],
    split_source_by_file: dict[Path, dict[str, Any]],
    report_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    image_check = verify_image_refs(chapters_dir, forbid_remote=True)
    failures: list[str] = []
    if image_check["missing"] or image_check["remote_refs"]:
        failures.append(f"Phase 3.2 requires clean local images after splitting: {image_check}")

    total_markers = 0
    total_resolved = 0
    total_images = 0
    unit_reports: list[dict[str, Any]] = []
    for unit in units:
        path = Path(unit.chapter_path)
        markers = phase30.scan_unit_markers(unit)
        images = phase30.local_image_refs(path)
        total_markers += len(markers)
        total_images += len(images)
        out_path = phase30.enrichment_path(wiki, slug, unit)
        unit_failures: list[str] = []
        resolved_meta = {"resolved": 0, "sections": 0}
        split_source = split_source_by_file.get(path.resolve())
        if split_source is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if markers:
                text, inherited_failures, inherited_resolved = render_inherited_vision_log(
                    wiki,
                    slug,
                    unit,
                    markers,
                    images,
                    split_source["unit_id"],
                    split_source["vision_log"],
                    split_source["marker_fields"],
                )
                out_path.write_text(text, encoding="utf-8")
                unit_failures.extend(inherited_failures)
                resolved_meta = {"resolved": inherited_resolved, "sections": len(markers)}
                validation_failures, validation_meta = phase30.validate_existing_log(out_path, markers)
                unit_failures.extend(validation_failures)
                resolved_meta = validation_meta
            else:
                out_path.write_text(phase30.render_log(slug, unit, markers, images, status="pass"), encoding="utf-8")
        else:
            if not markers:
                phase30.ensure_log(out_path, slug, unit, markers, images, status="pass")
            else:
                phase30.ensure_log(out_path, slug, unit, markers, images, status="pending")
                validation_failures, resolved_meta = phase30.validate_existing_log(out_path, markers)
                unit_failures.extend(validation_failures)
        total_resolved += resolved_meta["resolved"]
        failures.extend(f"{unit.unit_id}: {failure}" for failure in unit_failures)
        unit_reports.append(
            {
                "unit_id": unit.unit_id,
                "chapter_file": unit.chapter_path,
                "output": rel(out_path, wiki),
                "marker_count": len(markers),
                "resolved_markers": resolved_meta["resolved"],
                "local_image_refs": len(images),
                "markers": markers,
                "failures": unit_failures,
            }
        )

    report = {
        "status": "FAIL" if failures else "PASS",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "unit_count": len(units),
        "marker_count": total_markers,
        "resolved_markers": total_resolved,
        "local_image_refs": total_images,
        "image_check": image_check,
        "units": unit_reports,
        "failures": failures,
    }
    write_json(report_path, report)
    return report, failures


def regenerate_source_indexes(wiki: Path, slug: str, units: list[ExtractionUnit], report_path: Path) -> tuple[dict[str, Any], list[str]]:
    all_failures: list[str] = []
    unit_reports: list[dict[str, Any]] = []
    all_ids: list[str] = []
    for unit in units:
        blocks, failures = phase31.extract_blocks(unit, slug)
        if not blocks:
            failures.append(f"unit {unit.unit_id} has no block IDs")
        title = phase31.title_for_unit(Path(unit.chapter_path), unit.unit_id)
        out_path = phase31.source_index_path(wiki, slug, unit)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(phase31.render_source_index(slug, unit, blocks, title), encoding="utf-8")
        validation = phase31.validate_index(out_path, unit, blocks)
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
        all_failures.append(f"duplicate block IDs across units after Phase 3.2 split: {duplicates[:10]}")
    report = {
        "status": "FAIL" if all_failures else "PASS",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "unit_count": len(units),
        "total_block_ids": len(all_ids),
        "unique_block_ids": len(set(all_ids)),
        "units": unit_reports,
        "failures": all_failures,
    }
    write_json(report_path, report)
    return report, all_failures


def manifest_entry(raw_root: Path, unit: ExtractionUnit) -> dict[str, Any]:
    path = Path(unit.chapter_path)
    return {
        "chapter": unit.chapter_num,
        "unit_id": unit.unit_id,
        "part": unit.part_num,
        "title": phase31.title_for_unit(path, unit.unit_id),
        "file": rel(path, raw_root),
        "lines": line_count(path),
    }


def update_manifest(raw_root: Path, slug: str, units: list[ExtractionUnit], split_count: int, max_lines: int, split_window: int) -> Path:
    manifest_path = raw_root / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if split_count:
            backup = raw_root / "manifest.pre-phase-3.2.json"
            if not backup.exists():
                backup.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
    manifest.update(
        {
            "schema_version": int(manifest.get("schema_version", 1)),
            "slug": slug,
            "generated_at": utc_now(),
            "unit_count": len(units),
            "chapters": [manifest_entry(raw_root, unit) for unit in units],
            "phase_3_2_size_split": {
                "generated_at": utc_now(),
                "runner": RUNNER,
                "max_lines": max_lines,
                "overlap": 0,
                "split_window": split_window,
                "split_count": split_count,
            },
        }
    )
    write_json(manifest_path, manifest)
    return manifest_path


def validate_post_units(chapters_dir: Path, slug: str, max_lines: int) -> tuple[list[ExtractionUnit], list[str]]:
    failures: list[str] = []
    try:
        units = discover_current_units(chapters_dir, slug)
    except Exception as exc:
        return [], [str(exc)]
    for unit in units:
        count = line_count(Path(unit.chapter_path))
        if count > max_lines:
            failures.append(f"{unit.unit_id}: {count} lines after split; max is {max_lines}")
    return units, failures


def parse_args() -> argparse.Namespace:
    ap = pipeline_parser("Run Domain Library Phase 3.2 size-split hard gate", default=DEFAULT_WIKI)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--max-lines", type=int, default=2000)
    ap.add_argument("--split-window", type=int, default=100)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    report_path = raw_root / "size-split-report.json"
    vision_report_path = raw_root / "vision-enrichment-report.json"
    source_report_path = raw_root / "source-index-report.json"
    gates: dict[str, str] = {}
    completed: list[str] = []
    report: dict[str, Any] = {}

    try:
        if args.max_lines <= 0:
            raise ValueError("--max-lines must be positive")
        if args.split_window < 0:
            raise ValueError("--split-window must be non-negative")
        state, phase31_gate = preflight_phase31(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")

        units_before = discover_current_units(chapters_dir, slug)
        prereq_failures = validate_prerequisites(wiki, slug, units_before)
        if prereq_failures:
            raise RuntimeError("; ".join(prereq_failures[:10]))

        too_large = oversized_units(units_before, args.max_lines)
        nested = [row["unit"].unit_id for row in too_large if row["unit"].part_num is not None]
        if nested:
            raise RuntimeError(f"already split units still exceed max-lines; adjust upstream boundaries: {nested}")

        split_source_by_file: dict[Path, dict[str, Any]] = {}
        split_results: list[dict[str, Any]] = []
        archived: list[dict[str, str]] = []
        if too_large:
            old_units = [row["unit"] for row in too_large]
            old_info: dict[str, dict[str, Any]] = {}
            for unit in old_units:
                log_path = phase30.enrichment_path(wiki, slug, unit)
                old_info[unit.unit_id] = {
                    "unit_id": unit.unit_id,
                    "vision_log": log_path,
                    "marker_fields": marker_fields_by_key(log_path),
                }
            for row in too_large:
                unit = row["unit"]
                result = split_chapter(row["path"], args.max_lines, args.split_window, dry_run=False, slug=slug)
                split_results.append(result)
                for part in result["parts"]:
                    split_source_by_file[Path(part["file"]).resolve()] = old_info[unit.unit_id]
            archived = archive_superseded_team_dirs(wiki, slug, old_units)

        units_after, post_failures = validate_post_units(chapters_dir, slug, args.max_lines)
        if post_failures:
            raise RuntimeError("; ".join(post_failures[:10]))
        manifest_path = update_manifest(raw_root, slug, units_after, len(split_results), args.max_lines, args.split_window)

        vision_report: dict[str, Any] | None = None
        source_report: dict[str, Any] | None = None
        regen_failures: list[str] = []
        if split_results:
            vision_report, vision_failures = regenerate_vision_logs(wiki, slug, chapters_dir, units_after, split_source_by_file, vision_report_path)
            source_report, source_failures = regenerate_source_indexes(wiki, slug, units_after, source_report_path)
            regen_failures.extend(vision_failures)
            regen_failures.extend(source_failures)
        else:
            regen_failures.extend(validate_prerequisites(wiki, slug, units_after))
        if regen_failures:
            raise RuntimeError("; ".join(regen_failures[:10]))

        unit_rows = [
            {
                "unit_id": unit.unit_id,
                "chapter_file": rel(Path(unit.chapter_path), wiki),
                "lines": line_count(Path(unit.chapter_path)),
            }
            for unit in units_after
        ]
        report = {
            "status": "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "generated_by": RUNNER,
            "phase_3_1_gate": phase31_gate,
            "max_lines": args.max_lines,
            "overlap": 0,
            "split_window": args.split_window,
            "action": "split" if split_results else "no-op",
            "pre_unit_count": len(units_before),
            "post_unit_count": len(units_after),
            "oversized_count": len(too_large),
            "split_count": len(split_results),
            "manifest": rel(manifest_path, wiki),
            "vision_report": rel(vision_report_path, wiki) if vision_report is not None else "",
            "source_index_report": rel(source_report_path, wiki) if source_report is not None else "",
            "archived_team_dirs": archived,
            "split_results": split_results,
            "units": unit_rows,
            "failures": [],
        }
        write_json(report_path, report)

        phase32_gate = write_gate(
            wiki,
            slug,
            "3.2",
            "PASS",
            {
                "report": rel(report_path, wiki),
                "phase_3_1_gate": phase31_gate,
                "max_lines": args.max_lines,
                "overlap": 0,
                "split_window": args.split_window,
                "pre_unit_count": len(units_before),
                "post_unit_count": len(units_after),
                "split_count": len(split_results),
                "regenerated_prerequisites": bool(split_results),
            },
        )
        gates["3.2"] = rel(phase32_gate, wiki)
        if "3.2" not in completed:
            completed.append("3.2")
        write_state(wiki, slug, "READY_FOR_3.3", "3.2", completed, gates)
    except Exception as exc:
        if not report:
            report = {
                "status": "FAIL",
                "slug": slug,
                "generated_at": utc_now(),
                "generated_by": RUNNER,
                "max_lines": args.max_lines,
                "overlap": 0,
                "split_window": args.split_window,
                "failures": [str(exc)],
            }
        else:
            report["status"] = "FAIL"
            report["failures"] = [str(exc)]
        write_json(report_path, report)
        fail_gate = write_gate(wiki, slug, "3.2", "FAIL", {"reason": str(exc), "report": rel(report_path, wiki)})
        gates["3.2"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.2", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_3_2_gate": gates["3.2"],
                "report": rel(report_path, wiki),
                "action": report["action"],
                "pre_unit_count": report["pre_unit_count"],
                "post_unit_count": report["post_unit_count"],
                "split_count": report["split_count"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
