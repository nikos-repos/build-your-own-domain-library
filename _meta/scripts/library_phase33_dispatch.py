#!/usr/bin/env python3
"""Domain Library Phase 3.3 specialist-dispatch gate.

This runner cannot launch subagents from Python. It owns the
deterministic parts around the agent-runtime dispatch action:

1. `--prepare` validates Phase 3.2 and the shipped lane prompt contracts,
   writes runtime-neutral invocation payloads plus per-task
   assignments for the current unit/lane graph, and marks pipeline state
   IN_PROGRESS for Phase 3.3. It does not emit a generic `task_tool_payload`;
   the current operator chooses its native subagent mechanism.
2. The operator launches the generated assignments.
3. `--record --dispatch-result <json>` validates every generated task has a
   real runtime task/job ids plus actual runtime/model metadata and outputs,
   writes the Phase 3.3 PASS gate, and advances state to READY_FOR_3.4.

Phase 3.4 owns specialist output and schema validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from domain_library.paths import default_wiki
from domain_library.pipeline.cli import pipeline_parser
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts import library_phase31_source_index as phase31
from _meta.scripts.extraction_units import ExtractionUnit, discover_units

DEFAULT_WIKI = default_wiki()
RUNNER = "library_phase33_dispatch.py"

# Lane identity comes from _meta/config/domain.json; populated below after imports.
LANES: dict[str, dict[str, Any]] = {}

ORCHESTRATOR_OUTPUTS = ("orchestrator-vision-enrichment.md", "orchestrator-source-index.md")

from domain_library.pipeline.common import (  # shared plumbing — audit T10
    extraction_root,
    gate_path,
    load_state,
    read_json,
    record_cost,
    rel,
    resolve_path,
    schema_dir,
    state_path,
    utc_now,
    write_gate,
    write_json,
)
from domain_library.pipeline import common as pipeline_common


def _load_lanes(wiki: Path) -> None:
    LANES.clear()
    LANES.update(pipeline_common.configured_lanes(wiki))


_load_lanes(DEFAULT_WIKI)


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "specialist-dispatch-report.json"


def plan_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "specialist-dispatch-plan.json"


def assignment_dir(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "dispatch" / "phase-3.3-assignments"


def preflight_phase32(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.2")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.2 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.2 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.2" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.2 complete")
    if state.get("status") not in {"READY_FOR_3.3", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.3: {state.get('status')}")
    size_report = gate_data.get("report")
    if isinstance(size_report, str) and size_report:
        size_path = wiki / size_report if not Path(size_report).is_absolute() else Path(size_report)
        if not size_path.exists():
            raise FileNotFoundError(f"Phase 3.2 size report not found: {size_path}")
        size_data = read_json(size_path)
        if size_data.get("status") != "PASS":
            raise RuntimeError(f"Phase 3.2 size report is not PASS: {size_path}")
        if size_data.get("overlap") != 0:
            raise RuntimeError("Phase 3.2 size report did not enforce zero overlap")
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


def title_for_unit(unit: ExtractionUnit) -> str:
    return phase31.title_for_unit(Path(unit.chapter_path), unit.unit_id)


def validate_source_index(path: Path, unit: ExtractionUnit) -> dict[str, Any]:
    data = phase31.parse_source_index(path)
    if data.get("unit_id") != unit.unit_id:
        raise RuntimeError(f"source index unit mismatch for {unit.unit_id}: {path}")
    blocks = data.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise RuntimeError(f"source index has no blocks for {unit.unit_id}: {path}")
    return data


def validate_prerequisites(wiki: Path, slug: str, units: list[ExtractionUnit]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for unit in units:
        team_dir = extraction_root(wiki, slug) / f"team-{unit.unit_id}"
        if not team_dir.exists():
            raise FileNotFoundError(f"team directory missing for {unit.unit_id}: {team_dir}")
        for filename in ORCHESTRATOR_OUTPUTS:
            path = team_dir / filename
            if not path.exists() or path.stat().st_size == 0:
                raise FileNotFoundError(f"required orchestrator prerequisite missing or empty: {path}")
        source_data = validate_source_index(team_dir / "orchestrator-source-index.md", unit)
        rows.append(
            {
                "unit_id": unit.unit_id,
                "chapter_file": rel(Path(unit.chapter_path), wiki),
                "team_dir": rel(team_dir, wiki),
                "chapter": unit.chapter_num,
                "title": title_for_unit(unit),
                "source_index_blocks": len(source_data.get("blocks", [])),
            }
        )
    return rows


def parse_agent_frontmatter(text: str, path: Path) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        raise RuntimeError(f"agent profile missing frontmatter: {path}")
    end = text.find("\n---", 4)
    if end == -1:
        raise RuntimeError(f"agent profile frontmatter is not closed: {path}")
    raw_frontmatter = text[4:end]
    body = text[end + 4 :].strip()
    fields: dict[str, str] = {}
    for line in raw_frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, body


def active_agent_profile_dir() -> Path:
    override = os.environ.get("AGENT_PROFILE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (default_wiki() / "agents" / "library-workers").resolve()


def validate_agent_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    agent_dir = active_agent_profile_dir()
    for lane, spec in LANES.items():
        path = agent_dir / spec["agent_profile"]
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(f"agent profile for {lane} missing or empty: {path}")
        fields, body = parse_agent_frontmatter(path.read_text(encoding="utf-8"), path)
        if fields.get("name") != lane:
            raise RuntimeError(f"agent profile name mismatch for {lane}: {fields.get('name')!r}")
        if not fields.get("description"):
            raise RuntimeError(f"agent profile missing description: {path}")
        if not body:
            raise RuntimeError(f"agent profile system prompt is empty: {path}")
        profiles[lane] = {"path": str(path), "name": lane, "description": fields["description"]}
    return profiles


def camel(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[^A-Za-z0-9]+", value) if part)


def lane_task_id(unit_id: str, lane: str) -> str:
    base = f"{camel(lane)}{camel(unit_id)}"
    if len(base) <= 32:
        return base
    digest = hashlib.sha1(f"{lane}:{unit_id}".encode("utf-8")).hexdigest()[:6].upper()
    return f"{base[:26]}{digest}"[:32]


def schema_output_for(wiki: Path, slug: str, unit: ExtractionUnit, lane: str) -> Path:
    return schema_dir(wiki, slug) / f"{unit.unit_id}-{LANES[lane]['schema_output_suffix']}"


def output_for(wiki: Path, slug: str, unit: ExtractionUnit, lane: str) -> Path:
    return extraction_root(wiki, slug) / f"team-{unit.unit_id}" / LANES[lane]["output"]


def assignment_path_for(wiki: Path, slug: str, task_id: str) -> Path:
    return assignment_dir(wiki, slug) / f"{task_id}.md"


def render_assignment(wiki: Path, slug: str, unit: ExtractionUnit, lane: str) -> str:
    spec = LANES[lane]
    team_dir = extraction_root(wiki, slug) / f"team-{unit.unit_id}"
    markdown_output = output_for(wiki, slug, unit, lane)
    schema_output = schema_output_for(wiki, slug, unit, lane)
    source_index = team_dir / "orchestrator-source-index.md"
    vision_log = team_dir / "orchestrator-vision-enrichment.md"
    chapter_file = Path(unit.chapter_path)
    title = title_for_unit(unit)
    chapter_num = unit.chapter_num
    chapter_rel = rel(chapter_file, wiki)
    embed_target = chapter_rel[:-3] if chapter_rel.endswith(".md") else chapter_rel
    return f"""# Target
- Source slug: `{slug}`
- Unit: `{unit.unit_id}` / chapter `{chapter_num}` / `{title}`
- Named lane worker profile: `{spec['profile']}`
- Chapter markdown: `{chapter_rel}`
- Embed target (use before `#^` in every block embed/link): `{embed_target}`
- Orchestrator source index: `{rel(source_index, wiki)}`
- Orchestrator vision log: `{rel(vision_log, wiki)}`
- Markdown output: `{rel(markdown_output, wiki)}`
- Schema JSON draft output: `{rel(schema_output, wiki)}`
- Non-goals: do not edit chapter files, orchestrator files, other lane outputs, gates, manifests, or wiki concept pages.

# Change
1. Follow the active named lane worker profile `{spec['profile']}`.
2. Read the two orchestrator prerequisite files before writing.
3. Read only the source chapter ranges needed for same-slug block IDs in the source index category `{spec['focus_category']}` plus any full-chapter search explicitly required by the lane-agent profile.
4. Write `{rel(markdown_output, wiki)}` following the lane-agent profile exactly.
5. Also write `{rel(schema_output, wiki)}` as a real JSON object shaped for `_meta/scripts/schemas/extraction_schema.py`: `source`, `chapter`, `chapter_title`, `extracted_at`, `concepts`, `entities`, `formulas`, and `claims`.
6. Every definition/formula/claim/block reference in both outputs must cite actual same-slug block IDs from `{rel(source_index, wiki)}` and the chapter text. Do not invent quotes, equations, examples, entities, relationships, or block IDs.
7. If the profile's requested content is not present in this unit, say that explicitly in the markdown with the closest relevant source evidence; do not fabricate replacement content.
8. Skip all project-wide commands, gates, tests, formatters, and audits. This is a content extraction task only.

# Evidence hygiene
- Block embeds must be exactly `> ![[{embed_target}#^blockID]]`; copy `blockID` without square brackets and without duplicating closing brackets.
- Provenance Relations must target chapter block links, e.g. `- extracted_from::[[{embed_target}#^blockID|^chNN-NNNN]]`; never use `[[{slug}]]`, `[[source]]`, a unit id, or a partial path as evidence.
- Use only predicates allowed by `PAGE_SCHEMA.md`; if a concept-only relation is explicitly source-supported, use `relates_to::`, not `related_to::`.
- JSON `block_id` and `block_ids` values must be bare IDs like `{slug}-chNN-NNNN`, with no leading `^`, brackets, aliases, or path fragments.

# Acceptance
- `{rel(markdown_output, wiki)}` exists, is non-empty, and contains the lane-profile-required section headers for `{lane}`.
- `{rel(schema_output, wiki)}` exists, is non-empty JSON, and uses only same-slug block IDs matching `{slug}-chNN-NNNN`.
- Output text is source-grounded: every substantive claim has a block citation or embed.
- No placeholders, mocks, TODOs, fake fallbacks, or generic boilerplate.
- Print the lane profile's required `COMPLETED: ... STOP.` line after writing the files.
"""


def task_record(wiki: Path, slug: str, unit: ExtractionUnit, lane: str) -> dict[str, Any]:
    spec = LANES[lane]
    task_id = lane_task_id(unit.unit_id, lane)
    assignment_path = assignment_path_for(wiki, slug, task_id)
    assignment_text = render_assignment(wiki, slug, unit, lane)
    assignment_path.parent.mkdir(parents=True, exist_ok=True)
    assignment_path.write_text(assignment_text, encoding="utf-8")
    return {
        "id": task_id,
        "description": f"{lane} {unit.unit_id}",
        "assignment": assignment_text,
        "task_key": f"{slug}:{unit.unit_id}:{lane}",
        "idempotency_key": f"{slug}:{unit.unit_id}:{lane}",
        "dispatch_model": "runtime-subagent",
        "agent": spec["profile"],
        "agent_type": spec["profile"],
        "owner": "specialist",
        "lane": lane,
        "profile": spec["profile"],
        "agent_profile": spec["agent_profile"],
        "unit_id": unit.unit_id,
        "chapter": unit.chapter_num,
        "chapter_file": rel(Path(unit.chapter_path), wiki),
        "team_dir": rel(extraction_root(wiki, slug) / f"team-{unit.unit_id}", wiki),
        "assignment_file": rel(assignment_path, wiki),
        "markdown_output": rel(output_for(wiki, slug, unit, lane), wiki),
        "schema_output": rel(schema_output_for(wiki, slug, unit, lane), wiki),
        "dependencies": [f"{slug}:{unit.unit_id}:orchestrator:vision_enrichment", f"{slug}:{unit.unit_id}:orchestrator:source_index"],
        "declared_lane_dependencies": [],
        "acceptance_criteria": spec["acceptance"],
    }


def task_tool_context(wiki: Path, slug: str) -> str:
    return (
        "# Goal\n"
        f"Run specialist extraction for Domain Library slug `{slug}`.\n"
        "# Constraints\n"
        f"Active repo/wiki: `{wiki}`. Use named specialist lanes only. Do not use external board tooling. "
        "Do not edit orchestrator prerequisite files, phase gates, manifests, or wiki concept pages. "
        "Do not run project-wide tests, gates, formatters, audits, or build commands. "
        "Every output must be source-grounded in same-slug block IDs from the orchestrator source index and chapter text. "
        "No placeholders, mocks, fabricated quotes, fabricated equations, or fake block IDs.\n"
        "# Contract\n"
        "Each task writes exactly its lane markdown file and schema JSON draft, then stops. Phase 3.4 performs verification and schema validation."
    )


def agent_invocation_payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "description": task["description"],
        "profile": task["agent_profile"],
        "assignment": task["assignment"],
        "expected_outputs": [task["markdown_output"], task["schema_output"]],
    }


def chapter_task_payload_batches(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chapters: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for task in tasks:
        chapter = str(task["chapter"])
        if chapter not in chapters:
            chapters[chapter] = []
            order.append(chapter)
        chapters[chapter].append(task)
    batches: list[dict[str, Any]] = []
    for index, chapter in enumerate(order, start=1):
        chunk = chapters[chapter]
        unit_ids = sorted({str(task["unit_id"]) for task in chunk})
        batches.append(
            {
                "batch": index,
                "batch_id": f"chapter-{int(chapter):02d}",
                "chapter": int(chapter),
                "unit_ids": unit_ids,
                "task_count": len(chunk),
                "task_ids": [str(task["id"]) for task in chunk],
                "agent_invocations": [agent_invocation_payload(task) for task in chunk],
            }
        )
    return batches




def build_prepare_payload(
    wiki: Path,
    slug: str,
    units: list[ExtractionUnit],
    unit_rows: list[dict[str, Any]],
    batch_size: int,
    agent_profiles: dict[str, dict[str, str]],
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for unit in units:
        for lane in LANES:
            task = task_record(wiki, slug, unit, lane)
            tasks.append(task)
    task_ids: dict[str, dict[str, str]] = {}
    for item in tasks:
        task_ids.setdefault(item["unit_id"], {})[item["lane"]] = item["id"]
    context = task_tool_context(wiki, slug)
    chapter_batches = chapter_task_payload_batches(tasks)
    dispatch_model = "runtime-native-subagents"
    lanes = {}
    for lane, spec in LANES.items():
        lanes[lane] = {k: v for k, v in spec.items() if k != "schema_output_suffix"}
    return {
        "schema_version": 1,
        "status": "READY_FOR_DISPATCH",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "dispatch_model": dispatch_model,
        "agent_mode": "runtime-neutral-prompt-contracts",
        "agents": list(LANES),
        "agent_profiles": agent_profiles,
        "unit_mode": "chapter-batches",
        "lanes": lanes,
        "unit_count": len(units),
        "lane_count": len(LANES),
        "task_count": len(tasks),
        "task_ids": task_ids,
        "units": unit_rows,
        "context": context,
        "tasks": tasks,
        "batch_size": batch_size,
        "chapter_batch_count": len(chapter_batches),
        "chapter_task_payload_batches": chapter_batches,
        "record_command": f"python3 _meta/scripts/{RUNNER} --slug {slug} --record --dispatch-result _meta/extractions/{slug}/dispatch-result.json",
    }


def fail_if_existing_outputs(wiki: Path, slug: str, units: list[ExtractionUnit], allow_existing_outputs: bool) -> None:
    if allow_existing_outputs:
        return
    existing: list[str] = []
    for unit in units:
        for lane in LANES:
            for path in (output_for(wiki, slug, unit, lane), schema_output_for(wiki, slug, unit, lane)):
                if path.exists():
                    existing.append(rel(path, wiki))
    if existing:
        raise FileExistsError(f"specialist outputs already exist; use --allow-existing-outputs only for intentional recovery: {existing[:10]}")


def prepare(args: argparse.Namespace) -> None:
    wiki = Path(args.wiki).resolve()
    _load_lanes(wiki)
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase32_gate = preflight_phase32(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
        agent_profiles = validate_agent_profiles()
        units = discover_current_units(chapters_dir, slug)
        fail_if_existing_outputs(wiki, slug, units, args.allow_existing_outputs)
        unit_rows = validate_prerequisites(wiki, slug, units)
        payload = build_prepare_payload(wiki, slug, units, unit_rows, args.batch_size, agent_profiles)
        payload["phase_3_2_gate"] = phase32_gate
        write_json(plan_path(wiki, slug), payload)
        ready_report = {k: v for k, v in payload.items() if k != "task_tool_payload"}
        ready_report["status"] = "READY_FOR_DISPATCH"
        ready_report["plan"] = rel(plan_path(wiki, slug), wiki)
        write_json(report_path(wiki, slug), ready_report)
        write_state(wiki, slug, "IN_PROGRESS", "3.3", completed, gates)
    except Exception as exc:
        fail_gate = write_gate(wiki, slug, "3.3", "FAIL", {"reason": str(exc), "stage": "prepare"})
        gates["3.3"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.3", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "READY_FOR_DISPATCH",
                "slug": slug,
                "plan": rel(plan_path(wiki, slug), wiki),
                "report": rel(report_path(wiki, slug), wiki),
                "task_count": payload["task_count"],
                "unit_count": payload["unit_count"],
                "chapter_batch_count": payload["chapter_batch_count"],
                "agent_mode": payload["agent_mode"],
            },
            indent=2,
        )
    )


def normalize_dispatch_records(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    raw_jobs = data.get("jobs")
    if isinstance(raw_jobs, dict):
        for key, value in raw_jobs.items():
            if isinstance(value, str) and value.strip():
                records[str(key)] = {"id": str(key), "job_id": value.strip()}
            elif isinstance(value, dict):
                records[str(key)] = {"id": str(key), **value}
    for raw_tasks in (data.get("tasks"), data.get("results"), data.get("runs")):
        if not isinstance(raw_tasks, list):
            continue
        for item in raw_tasks:
            if not isinstance(item, dict):
                continue
            task_id = item.get("id") or item.get("planned_task_id") or item.get("task")
            if not isinstance(task_id, str) or not task_id.strip():
                continue
            record = records.setdefault(task_id, {"id": task_id})
            record.update(item)
            aliases = {
                "job_id": ("job_id", "run_id", "job"),
                "runtime_task_id": ("runtime_task_id", "task_id", "native_task_id"),
                "runtime": ("runtime", "actual_runtime_tool", "launcher"),
                "model": ("model", "actual_model", "model_id"),
            }
            for target, names in aliases.items():
                value = next((item.get(name) for name in names if item.get(name)), None)
                if isinstance(value, str):
                    record[target] = value.strip()
    return records


def synthetic_id(planned_id: str, value: str) -> bool:
    return value == planned_id or bool(re.search(r"(^|[-_:])(fake|mock|test|synthetic|placeholder)([-_:]|$)", value, re.IGNORECASE))


def optional_tokens(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise RuntimeError(f"dispatch result {field} must be a non-negative number when present")
    return int(value)


def record(args: argparse.Namespace) -> None:
    wiki = Path(args.wiki).resolve()
    _load_lanes(wiki)
    slug = pipeline_common.validate_slug(args.slug)
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase32_gate = preflight_phase32(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        plan = plan_path(wiki, slug)
        if not plan.exists():
            raise FileNotFoundError(f"dispatch plan not found; run --prepare first: {plan}")
        payload = read_json(plan)
        if payload.get("status") != "READY_FOR_DISPATCH":
            raise RuntimeError(f"dispatch plan is not READY_FOR_DISPATCH: {plan}")
        dispatch_result_path = Path(args.dispatch_result)
        if not dispatch_result_path.is_absolute():
            dispatch_result_path = wiki / dispatch_result_path
        if not dispatch_result_path.exists():
            raise FileNotFoundError(f"dispatch result file not found: {dispatch_result_path}")
        dispatch_result = read_json(dispatch_result_path)
        if dispatch_result.get("slug") not in {None, slug}:
            raise RuntimeError(f"dispatch result slug mismatch: {dispatch_result.get('slug')} != {slug}")
        records = normalize_dispatch_records(dispatch_result)
        missing: list[str] = []
        tasks: list[dict[str, Any]] = []
        task_ids: dict[str, dict[str, str]] = {}
        for item in payload.get("tasks", []):
            if not isinstance(item, dict):
                continue
            task_id = str(item.get("id", ""))
            dispatch_record = records.get(task_id)
            if not dispatch_record:
                missing.append(task_id)
                continue
            job_id = str(dispatch_record.get("job_id") or "")
            runtime_task_id = str(dispatch_record.get("runtime_task_id") or "")
            runtime = str(dispatch_record.get("runtime") or "")
            model = str(dispatch_record.get("model") or "")
            if not all((job_id, runtime_task_id, runtime, model)):
                missing.append(task_id)
                continue
            if synthetic_id(task_id, job_id) or synthetic_id(task_id, runtime_task_id):
                raise RuntimeError(f"dispatch result contains synthetic identifier for {task_id}")
            missing_outputs = [path for path in (item["markdown_output"], item["schema_output"]) if not (wiki / path).is_file()]
            if missing_outputs:
                raise RuntimeError(f"dispatch task {task_id} missing outputs: {missing_outputs}")
            row = {k: v for k, v in item.items() if k != "assignment"}
            row["runtime_task_id"] = runtime_task_id
            row["job_id"] = job_id
            row["runtime"] = runtime
            row["model"] = model
            row["tokens_in"] = optional_tokens(dispatch_record.get("tokens_in"), "tokens_in")
            row["tokens_out"] = optional_tokens(dispatch_record.get("tokens_out"), "tokens_out")
            row["dispatch_status"] = "recorded"
            tasks.append(row)
            unit_id = str(row["unit_id"])
            lane = str(row["lane"])
            task_ids.setdefault(unit_id, {})[lane] = runtime_task_id
        if missing:
            raise RuntimeError(f"dispatch result missing runtime job ids for tasks: {missing[:10]}")
        if len(tasks) != int(payload.get("task_count", -1)):
            raise RuntimeError(f"recorded {len(tasks)} tasks but plan expected {payload.get('task_count')}")
        for row in tasks:
            if row["tokens_in"] is not None or row["tokens_out"] is not None:
                record_cost(
                    wiki,
                    slug,
                    "3.3",
                    str(row["runtime"]),
                    str(row["model"]),
                    tokens_in=row["tokens_in"],
                    tokens_out=row["tokens_out"],
                )

        final_report = {
            "schema_version": 1,
            "status": "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "generated_by": RUNNER,
            "dispatch_model": payload.get("dispatch_model"),
            "agent_mode": payload.get("agent_mode"),
            "agents": payload.get("agents", []),
            "agent_profiles": payload.get("agent_profiles", {}),
            "unit_mode": payload.get("unit_mode", "chapter-batches"),
            "phase_3_2_gate": phase32_gate,
            "plan": rel(plan, wiki),
            "dispatch_result": rel(dispatch_result_path, wiki),
            "unit_count": payload.get("unit_count"),
            "lane_count": payload.get("lane_count"),
            "task_count": len(tasks),
            "task_ids": task_ids,
            "lanes": payload.get("lanes", {}),
            "units": payload.get("units", []),
            "tasks": tasks,
            "failures": [],
        }
        write_json(report_path(wiki, slug), final_report)
        phase33_gate = write_gate(
            wiki,
            slug,
            "3.3",
            "PASS",
            {
                "report": rel(report_path(wiki, slug), wiki),
                "phase_3_2_gate": phase32_gate,
                "dispatch_model": payload.get("dispatch_model"),
                "unit_count": payload.get("unit_count"),
                "lane_count": payload.get("lane_count"),
                "task_count": len(tasks),
            },
        )
        gates["3.3"] = rel(phase33_gate, wiki)
        if "3.3" not in completed:
            completed.append("3.3")
        write_state(wiki, slug, "READY_FOR_3.4", "3.3", completed, gates)
    except Exception as exc:
        fail_gate = write_gate(wiki, slug, "3.3", "FAIL", {"reason": str(exc), "stage": "record"})
        gates["3.3"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.3", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_3_3_gate": gates["3.3"],
                "report": rel(report_path(wiki, slug), wiki),
                "task_count": len(tasks),
                "unit_count": payload.get("unit_count"),
                "agent_mode": payload.get("agent_mode"),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    ap = pipeline_parser("Prepare or record Domain Library Phase 3.3 specialist dispatch", default=DEFAULT_WIKI)
    ap.add_argument("--slug", required=True)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Validate prerequisites and write agent invocation payload")
    mode.add_argument("--record", action="store_true", help="Record runtime agent job IDs and write PASS gate")
    ap.add_argument("--dispatch-result", help="JSON file with runtime task ids/job ids, required with --record")
    ap.add_argument("--allow-existing-outputs", action="store_true", help="Allow pre-existing specialist outputs during prepare recovery")
    ap.add_argument("--batch-size", type=int, default=25, help="Maximum tasks per generated chapter-batch invocation payload")
    args = ap.parse_args()
    if not args.prepare and not args.record:
        args.prepare = True
    if args.batch_size < 1:
        ap.error("--batch-size must be >= 1")
    if args.record and not args.dispatch_result:
        ap.error("--record requires --dispatch-result")
    return args


def main() -> None:
    args = parse_args()
    if args.record:
        record(args)
    else:
        prepare(args)


if __name__ == "__main__":
    main()
