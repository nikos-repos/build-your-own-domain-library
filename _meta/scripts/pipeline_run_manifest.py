#!/usr/bin/env python3
"""Generate a Domain Library pipeline run manifest.

The manifest makes specialist lane discipline auditable after an ingest run:
every named lane output is tied to exactly one extraction unit, dependency
ordering, output file, verifier evidence, and orchestrator prerequisites.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from extraction_units import discover_units
    from pipeline_common import configured_lanes, load_domain_config, write_json
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extraction_units import discover_units
    from pipeline_common import configured_lanes, load_domain_config, write_json

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WIKI = SCRIPT_DIR.parents[1]

# Lane identity comes from _meta/config/domain.json.
LANES = configured_lanes(DEFAULT_WIKI)

ORCHESTRATOR_OUTPUTS = {
    "source_index": "orchestrator-source-index.md",
    "vision_enrichment": "orchestrator-vision-enrichment.md",
}


def load_json_maybe_embedded(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace")
    start = text.find("{")
    if start == -1:
        return {}
    return json.loads(text[start:])


def rel(path: Path, wiki: Path) -> str:
    try:
        return str(path.resolve().relative_to(wiki.resolve()))
    except Exception:
        return str(path)


def file_record(path: Path, wiki: Path, slug: str) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "path": rel(path, wiki),
        "exists": path.exists(),
        "size_bytes": 0,
        "block_id_count": 0,
    }
    if path.exists():
        rec["size_bytes"] = path.stat().st_size
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            rec["block_id_count"] = len(re.findall(rf"\^{re.escape(slug)}-ch\d{{2}}-\d+", text))
    return rec


def optional_file_record(path_value: Any, wiki: Path, slug: str) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(str(path_value))
    return file_record(path if path.is_absolute() else wiki / path, wiki, slug)


def verifier_lookup(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for row in report.get("results", []):
        out[(row.get("unit_id"), row.get("lane"))] = row
    return out


def dispatch_task_lookup(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out = {}
    for row in report.get("tasks", []):
        if isinstance(row, dict) and row.get("unit_id") and row.get("lane"):
            out[(str(row.get("unit_id")), str(row.get("lane")))] = row
    return out


def build_manifest(slug: str, wiki: Path, chapters_dir: Path, create_report: Path | None, verify_report: Path | None) -> dict[str, Any]:
    units = discover_units(chapters_dir, slug)
    create = load_json_maybe_embedded(create_report)
    verify = load_json_maybe_embedded(verify_report)
    task_ids = create.get("task_ids", {})
    dispatch_lookup = dispatch_task_lookup(create)
    unit_mode = create.get("unit_mode") or ("parallel" if create.get("dispatch_model") == "runtime-subagents" else "unknown")
    dispatch_model = create.get("dispatch_model") or "specialist-lanes"
    vlookup = verifier_lookup(verify)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "slug": slug,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": f"dir:{wiki}",
        "dispatch_model": dispatch_model,
        "tenant": load_domain_config(wiki)["tenant"],
        "unit_mode": unit_mode,
        "lanes": {lane: {"profile": spec["profile"], "output": spec["output"], "deps": spec["deps"]} for lane, spec in LANES.items()},
        "discipline_summary": {},
        "units": [],
        "tasks": [],
        "verification": {
            "specialist_verifier_status": verify.get("status"),
            "specialist_verifier_checked": verify.get("checked"),
            "specialist_verifier_failed": verify.get("failed"),
        },
        "source_reports": {
            "specialist_dispatch_report": rel(create_report, wiki) if create_report else None,
            "specialist_verification": rel(verify_report, wiki) if verify_report else None,
        },
    }

    task_count = 0
    actual_task_ids = 0
    missing_outputs = []
    lane_unit_pairs = set()

    prior_unit_tail: str | None = None
    for unit in units:
        team_dir = wiki / "_meta" / "extractions" / slug / f"team-{unit.unit_id}"
        unit_entry = {
            "unit_id": unit.unit_id,
            "chapter_file": rel(Path(unit.chapter_path), wiki),
            "team_dir": rel(team_dir, wiki),
            "orchestrator_prerequisites": {name: file_record(team_dir / fname, wiki, slug) for name, fname in ORCHESTRATOR_OUTPUTS.items()},
        }
        manifest["units"].append(unit_entry)
        # Orchestrator-owned pseudo tasks are included to make the dependency graph complete.
        for orch_name, fname in ORCHESTRATOR_OUTPUTS.items():
            out_file = team_dir / fname
            if out_file.exists():
                manifest["tasks"].append({
                    "task_key": f"{slug}:{unit.unit_id}:orchestrator:{orch_name}",
                    "task_id": None,
                    "idempotency_key": f"{slug}:{unit.unit_id}:orchestrator:{orch_name}",
                    "owner": "orchestrator",
                    "lane": f"orchestrator:{orch_name}",
                    "profile": "orchestrator",
                    "unit_id": unit.unit_id,
                    "chapter_file": rel(Path(unit.chapter_path), wiki),
                    "output": file_record(out_file, wiki, slug),
                    "dependencies": [],
                    "status": "completed" if out_file.exists() else "missing",
                    "verification": vlookup.get((unit.unit_id, "orchestrator"), {}),
                })
        unit_task_ids: dict[str, str] = task_ids.get(unit.unit_id, {})
        for lane_index, (lane, spec) in enumerate(LANES.items(), start=1):
            dispatch_row = dispatch_lookup.get((unit.unit_id, lane), {})
            tid = dispatch_row.get("runtime_task_id") or dispatch_row.get("job_id") or unit_task_ids.get(lane)
            actual_task_ids += 1 if tid else 0
            task_count += 1
            lane_unit_pairs.add((unit.unit_id, lane))
            output_path = team_dir / spec["output"]
            if dispatch_row.get("markdown_output"):
                candidate = Path(str(dispatch_row["markdown_output"]))
                output_path = candidate if candidate.is_absolute() else wiki / candidate
            if dispatch_row:
                deps = [str(x) for x in dispatch_row.get("dependencies", [])]
                declared_lane_dependencies = [str(x) for x in dispatch_row.get("declared_lane_dependencies", [])]
            else:
                deps = [unit_task_ids[d] for d in spec["deps"] if d in unit_task_ids]
                if unit_mode == "sequential" and lane_index == 1 and prior_unit_tail:
                    deps.append(prior_unit_tail)
                declared_lane_dependencies = spec["deps"]
            status = "completed" if output_path.exists() and not vlookup.get((unit.unit_id, lane), {}).get("issues") else "needs_review"
            if not output_path.exists():
                missing_outputs.append(rel(output_path, wiki))
            manifest["tasks"].append({
                "task_key": f"{slug}:{unit.unit_id}:{lane}",
                "task_id": tid,
                "idempotency_key": dispatch_row.get("idempotency_key") or f"{slug}:{unit.unit_id}:{lane}",
                "owner": "specialist",
                "lane": lane,
                "profile": spec["profile"],
                "unit_id": unit.unit_id,
                "chapter_file": rel(Path(unit.chapter_path), wiki),
                "output": file_record(output_path, wiki, slug),
                "schema_output": optional_file_record(dispatch_row.get("schema_output"), wiki, slug),
                "dependencies": deps,
                "declared_lane_dependencies": declared_lane_dependencies,
                "status": status,
                "verification": vlookup.get((unit.unit_id, lane), {}),
                "acceptance_criteria": dispatch_row.get("acceptance_criteria") or spec["minimums"],
            })
        prior_unit_tail = unit_task_ids.get("context") or prior_unit_tail

    expected_pairs = len(units) * len(LANES)
    manifest["discipline_summary"] = {
        "units": len(units),
        "named_lanes": list(LANES),
        "expected_specialist_outputs": expected_pairs,
        "actual_specialist_dispatch_ids": actual_task_ids,
        "unique_unit_lane_pairs": len(lane_unit_pairs),
        "one_lane_output_per_unit": len(lane_unit_pairs) == expected_pairs,
        "all_outputs_exist": not missing_outputs,
        "missing_outputs": missing_outputs,
        "specialist_failed_outputs": verify.get("failed"),
        "orchestrator_outputs_are_not_specialist_outputs": True,
    }
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate Domain Library pipeline-run-manifest.json")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    ap.add_argument("--chapters-dir", required=True)
    ap.add_argument("--specialist-dispatch-report")
    ap.add_argument("--specialist-verification")
    ap.add_argument("--output")
    args = ap.parse_args()

    wiki = Path(args.wiki)
    out = Path(args.output) if args.output else wiki / "_meta" / "extractions" / args.slug / "pipeline-run-manifest.json"
    manifest = build_manifest(
        slug=args.slug,
        wiki=wiki,
        chapters_dir=Path(args.chapters_dir),
        create_report=Path(args.specialist_dispatch_report) if args.specialist_dispatch_report else None,
        verify_report=Path(args.specialist_verification) if args.specialist_verification else None,
    )
    write_json(out, manifest)
    print(json.dumps({"output": str(out), "tasks": len(manifest["tasks"]), "discipline_summary": manifest["discipline_summary"]}, indent=2))


if __name__ == "__main__":
    main()
