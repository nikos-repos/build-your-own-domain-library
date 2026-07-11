#!/usr/bin/env python3
"""Domain Library Phase 3.4 specialist-output verification gate.

Phase 3.4 verifies specialist lane outputs from Phase 3.3. It deliberately
checks only lane markdown and schema JSON draft outputs; team presentation
validation belongs to Phase 3.5, fixing the old ordering mismatch.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = SCRIPT_DIR.parent / "schemas"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCHEMA_DIR))

import pipeline_run_manifest
import library_phase31_source_index as phase31
import library_phase33_dispatch as phase33
import wiki_integrity
from extraction_schema import validate_extraction_file
from extraction_units import ExtractionUnit, discover_units

DEFAULT_WIKI = SCRIPT_DIR.parents[1]
RUNNER = "library_phase34_verify.py"
BLOCK_ID_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)")
BRACKETED_BLOCK_ID_RE = re.compile(r"\^\[[a-z0-9-]+-ch\d+-\d+\]")
EXTRA_BRACKET_EMBED_RE = re.compile(r"!\[\[[^\]\n]+#\^[^\]\n]+\]\]\]")
BLOCK_PREDICATE_WITHOUT_ANCHOR_RE = re.compile(
    r"^-\s+(?:extracted_from|informed_by|validated_by|invalidated_by|warned_by|defined_by|formulated_by|illustrated_by|calibrated_by)::\[\[[^\]#]+\]\]",
    re.MULTILINE,
)
RELATED_TO_RE = re.compile(r"^-\s+related_to::", re.MULTILINE)

# Required sections come from _meta/config/domain.json lane required_sections; populated below after imports.
LANE_SECTIONS: dict[str, list[str]] = {}


from pipeline_common import (  # shared plumbing — audit T10
    SLOP_RE,
    extraction_root,
    gate_path,
    load_state,
    manifest_path,
    read_json,
    rel,
    resolve_path,
    schema_dir,
    state_path,
    utc_now,
    verification_path,
    write_gate,
    write_json,
)
import pipeline_common


def _load_lane_sections(wiki: Path) -> None:
    LANE_SECTIONS.clear()
    LANE_SECTIONS.update({lane_id: spec["required_sections"] for lane_id, spec in pipeline_common.configured_lanes(wiki).items()})


_load_lane_sections(DEFAULT_WIKI)


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def schema_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "schema-validation-report.json"


def validation_marker_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "_validation_passed"


def dispatch_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "specialist-dispatch-report.json"


def preflight_phase33(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.3")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.3 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.3 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.3" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.3 complete")
    if state.get("status") not in {"READY_FOR_3.4", "IN_PROGRESS", "FAILED"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.4: {state.get('status')}")
    if state.get("status") == "FAILED" and state.get("current_phase") != "3.4":
        raise RuntimeError(f"pipeline-state FAILED outside Phase 3.4 retry context: {state.get('current_phase')}")

    report_ref = gate_data.get("report") or rel(dispatch_report_path(wiki, slug), wiki)
    report_file = resolve_path(report_ref, wiki)
    if not report_file.exists():
        raise FileNotFoundError(f"Phase 3.3 dispatch report not found: {report_file}")
    dispatch_report = read_json(report_file)
    if dispatch_report.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.3 dispatch report is not PASS: {report_file}")
    allowed_dispatch_models = {"runtime-native-subagents"}
    if dispatch_report.get("dispatch_model") not in allowed_dispatch_models:
        raise RuntimeError(f"unexpected dispatch model: {dispatch_report.get('dispatch_model')}")
    if dispatch_report.get("agent_mode") != "runtime-neutral-prompt-contracts":
        raise RuntimeError(f"unexpected Phase 3.3 agent mode: {dispatch_report.get('agent_mode')}")
    return state, gate_data, dispatch_report, report_file


def discover_current_units(chapters_dir: Path, slug: str) -> list[ExtractionUnit]:
    units = discover_units(chapters_dir, slug)
    if not units:
        raise RuntimeError(f"no extraction units discovered in {chapters_dir}")
    active = {path.name for path in chapters_dir.glob("*.md") if ".orig." not in path.name}
    discovered = {unit.filename for unit in units}
    unmapped = sorted(active - discovered)
    if unmapped:
        raise RuntimeError(f"chapter markdown files do not map to extraction units: {unmapped}")
    return units


def dispatch_lookup(report: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in report.get("tasks", []):
        if isinstance(row, dict) and row.get("unit_id") and row.get("lane"):
            key = (str(row["unit_id"]), str(row["lane"]))
            if key in out:
                raise RuntimeError(f"duplicate dispatch task for {key}")
            out[key] = row
    return out


def source_blocks_for_unit(wiki: Path, slug: str, unit: ExtractionUnit) -> set[str]:
    index = extraction_root(wiki, slug) / f"team-{unit.unit_id}" / "orchestrator-source-index.md"
    if not index.exists() or index.stat().st_size == 0:
        raise FileNotFoundError(f"missing source index for {unit.unit_id}: {index}")
    data = phase31.parse_source_index(index)
    if data.get("unit_id") != unit.unit_id:
        raise RuntimeError(f"source index unit mismatch for {unit.unit_id}: {index}")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise RuntimeError(f"source index has no blocks for {unit.unit_id}: {index}")
    return {str(block.get("block_id")) for block in blocks if isinstance(block, dict) and block.get("block_id")}


def markdown_sections(text: str) -> set[str]:
    return {match.group(1).strip() for match in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)}


def extract_block_ids_from_text(text: str) -> list[str]:
    return BLOCK_ID_RE.findall(text)


def extract_block_ids_from_json(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "block_id" and isinstance(item, str):
                out.append(item)
            elif key == "block_ids" and isinstance(item, list):
                out.extend(str(x) for x in item if isinstance(x, str))
            else:
                out.extend(extract_block_ids_from_json(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(extract_block_ids_from_json(item))
    return out


def verify_markdown_output(path: Path, slug: str, lane: str, valid_blocks: set[str], vault_index: wiki_integrity.VaultIndex) -> dict[str, Any]:
    issues: list[str] = []
    block_ids: list[str] = []
    if not path.exists():
        return {"path": str(path), "exists": False, "size_bytes": 0, "block_id_count": 0, "issues": ["missing markdown output"]}
    size = path.stat().st_size
    if size == 0:
        issues.append("empty markdown output")
        text = ""
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    sections = markdown_sections(text)
    missing_sections = [section for section in LANE_SECTIONS[lane] if section not in sections]
    if missing_sections:
        issues.append(f"missing required sections: {missing_sections}")
    if lane == "math":
        extra_sections = sorted(section for section in sections if section != "Author's Formulation")
        if extra_sections:
            issues.append(f"math output has forbidden extra level-2 sections: {extra_sections}")
    slop = SLOP_RE.search(text)
    if slop:
        issues.append(f"slop/placeholder marker found: {slop.group(0)}")
    if BRACKETED_BLOCK_ID_RE.search(text):
        issues.append("evidence hygiene violation: bracketed block ID citation")
    if EXTRA_BRACKET_EMBED_RE.search(text):
        issues.append("evidence hygiene violation: malformed extra-bracket block embed")
    if BLOCK_PREDICATE_WITHOUT_ANCHOR_RE.search(text):
        issues.append("evidence hygiene violation: block evidence predicate without #^ anchor")
    if RELATED_TO_RE.search(text):
        issues.append("evidence hygiene violation: use relates_to::, not related_to::")
    block_ids = extract_block_ids_from_text(text)
    if not block_ids:
        issues.append("no block IDs cited in markdown output")
    wrong_slug = sorted({bid for bid in block_ids if not bid.startswith(f"{slug}-")})
    if wrong_slug:
        issues.append(f"wrong-slug block IDs in markdown output: {wrong_slug[:10]}")
    unknown = sorted({bid for bid in block_ids if bid.startswith(f"{slug}-") and bid not in valid_blocks})
    if unknown:
        issues.append(f"markdown cites block IDs outside unit source index: {unknown[:10]}")
    dead_links = [f for f in wiki_integrity.check_text(vault_index, text) if f["status"] != "ok"]
    if dead_links:
        sample = "; ".join(f"{f['raw']} [{f['status']}]" for f in dead_links[:5])
        issues.append(f"markdown has {len(dead_links)} unresolvable/non-canonical block links: {sample}")
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": size,
        "required_sections": LANE_SECTIONS[lane],
        "section_count": len(sections),
        "block_id_count": len(block_ids),
        "unique_block_ids": len(set(block_ids)),
        "issues": issues,
    }


def verify_schema_output(path: Path, slug: str, unit: ExtractionUnit, lane: str, valid_blocks: set[str]) -> dict[str, Any]:
    issues: list[str] = []
    data: Any = None
    if not path.exists():
        return {"path": str(path), "exists": False, "size_bytes": 0, "valid": False, "block_id_count": 0, "issues": ["missing schema JSON output"]}
    size = path.stat().st_size
    if size == 0:
        return {"path": str(path), "exists": True, "size_bytes": 0, "valid": False, "block_id_count": 0, "issues": ["empty schema JSON output"]}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"path": str(path), "exists": True, "size_bytes": size, "valid": False, "block_id_count": 0, "issues": [f"invalid JSON: {exc}"]}
    if not isinstance(data, dict):
        issues.append("schema output is not a JSON object")
    else:
        if data.get("source") != slug:
            issues.append(f"source mismatch: {data.get('source')} != {slug}")
        if data.get("chapter") != unit.chapter_num:
            issues.append(f"chapter mismatch: {data.get('chapter')} != {unit.chapter_num}")
    validation = validate_extraction_file(path, slug)
    if not validation.get("valid"):
        issues.append("extraction_schema.py validation failed")
        for key in ("pydantic_errors", "block_id_errors", "generic_test_failures"):
            values = validation.get(key, [])
            if values:
                issues.extend(f"{key}: {item}" for item in values[:5])
    block_ids = extract_block_ids_from_json(data)
    if not block_ids:
        issues.append("no block IDs cited in schema output")
    wrong_slug = sorted({bid for bid in block_ids if not bid.startswith(f"{slug}-")})
    if wrong_slug:
        issues.append(f"wrong-slug block IDs in schema output: {wrong_slug[:10]}")
    unknown = sorted({bid for bid in block_ids if bid.startswith(f"{slug}-") and bid not in valid_blocks})
    if unknown:
        issues.append(f"schema cites block IDs outside unit source index: {unknown[:10]}")
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": size,
        "valid": not issues,
        "block_id_count": len(block_ids),
        "unique_block_ids": len(set(block_ids)),
        "schema_validation": validation,
        "issues": issues,
    }


def verify_dispatch_report(wiki: Path, slug: str, dispatch_report: dict[str, Any], units: list[ExtractionUnit]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    lookup = dispatch_lookup(dispatch_report)
    failures: list[str] = []
    expected = {(unit.unit_id, lane) for unit in units for lane in phase33.LANES}
    actual = set(lookup)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        failures.append(f"dispatch report missing unit/lane tasks: {missing[:10]}")
    if extra:
        failures.append(f"dispatch report has stale/extra unit/lane tasks: {extra[:10]}")
    for key in sorted(expected & actual):
        row = lookup[key]
        for field in ("runtime_task_id", "job_id", "runtime", "model"):
            if not row.get(field):
                failures.append(f"{key}: missing recorded {field}")
        if not row.get("idempotency_key"):
            failures.append(f"{key}: missing idempotency key")
        if not row.get("markdown_output"):
            failures.append(f"{key}: missing markdown output path")
        if not row.get("schema_output"):
            failures.append(f"{key}: missing schema output path")
        assignment = row.get("assignment_file")
        if not assignment or not resolve_path(assignment, wiki).exists():
            failures.append(f"{key}: missing assignment file")
    return lookup, failures


def write_validation_marker(path: Path, slug: str, schema_report: Path, checked: int) -> None:
    path.write_text(
        "\n".join(
            [
                "status: PASS",
                f"slug: {slug}",
                f"validated_by: {RUNNER}",
                f"schema_report: {schema_report}",
                f"checked_schema_files: {checked}",
                f"generated_at: {utc_now()}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def remove_stale_validation_marker(wiki: Path, slug: str) -> None:
    marker = validation_marker_path(wiki, slug)
    if marker.exists():
        marker.unlink()


def run_verification(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any], Path, Path, list[str]]:
    _state, _phase33_gate, dispatch_report, dispatch_report_file = preflight_phase33(wiki, slug)
    chapters_dir = wiki / "raw" / "papers" / slug / "chapters"
    if not chapters_dir.exists():
        raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
    units = discover_current_units(chapters_dir, slug)
    lookup, dispatch_failures = verify_dispatch_report(wiki, slug, dispatch_report, units)
    valid_blocks_by_unit = {unit.unit_id: source_blocks_for_unit(wiki, slug, unit) for unit in units}
    vault_index = wiki_integrity.build_vault_index(wiki)
    expected_schema_paths: set[Path] = set()
    results: list[dict[str, Any]] = []
    failures: list[str] = list(dispatch_failures)

    for unit in units:
        for lane in phase33.LANES:
            row = lookup.get((unit.unit_id, lane), {})
            markdown_path = resolve_path(row.get("markdown_output") or f"_meta/extractions/{slug}/team-{unit.unit_id}/{phase33.LANES[lane]['output']}", wiki)
            schema_path = resolve_path(row.get("schema_output") or f"_meta/extractions/{slug}/schema/{unit.unit_id}-{lane}.json", wiki)
            expected_schema_paths.add(schema_path.resolve())
            valid_blocks = valid_blocks_by_unit[unit.unit_id]
            markdown = verify_markdown_output(markdown_path, slug, lane, valid_blocks, vault_index)
            schema = verify_schema_output(schema_path, slug, unit, lane, valid_blocks)
            issues = list(markdown["issues"]) + list(schema["issues"])
            if issues:
                failures.extend(f"{unit.unit_id}/{lane}: {issue}" for issue in issues)
            results.append(
                {
                    "unit_id": unit.unit_id,
                    "lane": lane,
                    "runtime_task_id": row.get("runtime_task_id"),
                    "job_id": row.get("job_id"),
                    "runtime": row.get("runtime"),
                    "model": row.get("model"),
                    "markdown_output": rel(markdown_path, wiki),
                    "schema_output": rel(schema_path, wiki),
                    "markdown": {**markdown, "path": rel(markdown_path, wiki)},
                    "schema": {**schema, "path": rel(schema_path, wiki)},
                    "issues": issues,
                }
            )

    schema_root = schema_dir(wiki, slug)
    actual_schema_paths = {path.resolve() for path in schema_root.glob("*.json") if not path.name.startswith("_")} if schema_root.exists() else set()
    unexpected = sorted(actual_schema_paths - expected_schema_paths)
    missing_schema = sorted(expected_schema_paths - actual_schema_paths)
    if unexpected:
        failures.append(f"unexpected schema JSON files not declared by dispatch: {[rel(path, wiki) for path in unexpected[:10]]}")
    if missing_schema:
        failures.append(f"missing declared schema JSON files: {[rel(path, wiki) for path in missing_schema[:10]]}")

    schema_details = [row["schema"]["schema_validation"] for row in results if row["schema"].get("schema_validation")]
    valid_count = sum(1 for detail in schema_details if detail.get("valid"))
    schema_report = {
        "status": "PASS" if valid_count == len(schema_details) and len(schema_details) == len(expected_schema_paths) and not unexpected and not missing_schema else "FAIL",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "schema_dir": rel(schema_root, wiki),
        "expected": len(expected_schema_paths),
        "total": len(schema_details),
        "valid": valid_count,
        "invalid": len(schema_details) - valid_count,
        "unexpected_files": [rel(path, wiki) for path in unexpected],
        "missing_files": [rel(path, wiki) for path in missing_schema],
        "details": schema_details,
    }
    if schema_report["status"] != "PASS":
        failures.append("schema validation batch failed")

    verification = {
        "schema_version": 1,
        "status": "FAIL" if failures else "PASS",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "dispatch_model": dispatch_report.get("dispatch_model"),
        "agent_mode": dispatch_report.get("agent_mode"),
        "dispatch_report": rel(dispatch_report_file, wiki),
        "checked": len(results),
        "failed": sum(1 for row in results if row["issues"]),
        "unit_count": len(units),
        "lane_count": len(phase33.LANES),
        "schema_validation_report": rel(schema_report_path(wiki, slug), wiki),
        "results": results,
        "failures": failures,
    }
    return verification, schema_report, chapters_dir, dispatch_report_file, failures


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 3.4 specialist output and schema verification gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    _load_lane_sections(wiki)
    phase33._load_lanes(wiki)
    slug = pipeline_common.validate_slug(args.slug)
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state = load_state(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        verification, schema_report, chapters_dir, dispatch_report_file, failures = run_verification(wiki, slug)
        write_json(verification_path(wiki, slug), verification)
        write_json(schema_report_path(wiki, slug), schema_report)
        manifest = pipeline_run_manifest.build_manifest(
            slug=slug,
            wiki=wiki,
            chapters_dir=chapters_dir,
            create_report=dispatch_report_file,
            verify_report=verification_path(wiki, slug),
        )
        write_json(manifest_path(wiki, slug), manifest)
        if failures:
            remove_stale_validation_marker(wiki, slug)
            raise RuntimeError(f"Phase 3.4 verification failed with {len(failures)} issue(s)")
        marker = validation_marker_path(wiki, slug)
        write_validation_marker(marker, slug, schema_report_path(wiki, slug), schema_report["total"])
        phase34_gate = write_gate(
            wiki,
            slug,
            "3.4",
            "PASS",
            {
                "verification_report": rel(verification_path(wiki, slug), wiki),
                "schema_validation_report": rel(schema_report_path(wiki, slug), wiki),
                "pipeline_run_manifest": rel(manifest_path(wiki, slug), wiki),
                "validation_marker": rel(marker, wiki),
                "checked": verification["checked"],
                "failed": verification["failed"],
                "schema_valid": schema_report["valid"],
            },
        )
        gates["3.4"] = rel(phase34_gate, wiki)
        if "3.4" not in completed:
            completed.append("3.4")
        write_state(wiki, slug, "READY_FOR_3.5", "3.4", completed, gates)
    except Exception as exc:
        remove_stale_validation_marker(wiki, slug)
        fail_gate = write_gate(wiki, slug, "3.4", "FAIL", {"reason": str(exc), "verification_report": rel(verification_path(wiki, slug), wiki)})
        gates["3.4"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.4", completed, gates)
        if not verification_path(wiki, slug).exists():
            write_json(
                verification_path(wiki, slug),
                {
                    "schema_version": 1,
                    "status": "FAIL",
                    "slug": slug,
                    "generated_at": utc_now(),
                    "generated_by": RUNNER,
                    "checked": 0,
                    "failed": 0,
                    "results": [],
                    "failures": [str(exc)],
                },
            )
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_3_4_gate": gates["3.4"],
                "verification_report": rel(verification_path(wiki, slug), wiki),
                "schema_validation_report": rel(schema_report_path(wiki, slug), wiki),
                "pipeline_run_manifest": rel(manifest_path(wiki, slug), wiki),
                "checked": verification["checked"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
