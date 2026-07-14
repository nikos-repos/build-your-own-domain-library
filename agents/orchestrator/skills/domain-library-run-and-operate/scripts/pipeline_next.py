#!/usr/bin/env python3
"""Unified state runner for the Domain-Library ingest pipeline.

One question, one answer: "what is the exact next command for this slug?"

Agent drift — running phases out of order, rerunning finished phases with
--force, treating a prepare step as a PASS, or inventing commands — has caused
most major failures in this project's history. This tool removes the need to
guess: it reads `_meta/extractions/<slug>/pipeline-state.json` plus the gate
JSONs and prints the single canonical next action, or a DRIFT report when the
recorded state and the on-disk gates disagree.

Usage (from the wiki/library root):
    python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --slug <slug>
    python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --all
    python3 agents/orchestrator/skills/domain-library-run-and-operate/scripts/pipeline_next.py --slug <slug> --json

Exit codes: 0 = clear next step; 2 = drift/blocked (fix before proceeding);
1 = usage error. Fail closed: an unknown status is DRIFT, not a guess.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "_meta" / "scripts"))
from pipeline_common import validate_slug

# status written by each runner -> (next owner, exact next command template)
# Command strings mirror agents/orchestrator/skills/domain-library-ingest-pipeline/SKILL.md ("Active
# command table"); if you change a runner's CLI, update both in one change.
NEXT = {
    "READY_FOR_2": "python3 _meta/scripts/library_phase2_chapters.py --slug {slug}",
    "READY_FOR_2.1": "python3 _meta/scripts/library_phase2_chapters.py --slug {slug}",
    "READY_FOR_2.2": "python3 _meta/scripts/library_phase2_chapters.py --slug {slug}",
    "READY_FOR_2.3": "python3 _meta/scripts/library_phase23_blocks.py --slug {slug}",
    "READY_FOR_2.4": "python3 _meta/scripts/library_phase24_images.py --slug {slug}",
    "READY_FOR_3.0": "python3 _meta/scripts/library_phase30_vision.py --slug {slug}",
    "READY_FOR_3.1": "python3 _meta/scripts/library_phase31_source_index.py --slug {slug}",
    "READY_FOR_3.2": "python3 _meta/scripts/library_phase32_size_split.py --slug {slug}",
    "READY_FOR_3.3": (
        "python3 _meta/scripts/library_phase33_dispatch.py --slug {slug} --prepare\n"
        "  then: dispatch specialist agents per agents/orchestrator/skills/domain-library-ingest-pipeline/references/specialist-dispatch-protocol.md\n"
        "  then: python3 _meta/scripts/library_phase33_dispatch.py --slug {slug} --record "
        "--dispatch-result _meta/extractions/{slug}/dispatch-result.json"
    ),
    "READY_FOR_3.4": "python3 _meta/scripts/library_phase34_verify.py --slug {slug}",
    "READY_FOR_3.5": "python3 _meta/scripts/library_phase35_presentations.py --slug {slug}",
    "READY_FOR_4": "python3 _meta/scripts/library_phase4_merge_score.py --slug {slug} --prepare",
    "AWAITING_USER_CONFIRMATION": (
        "HUMAN GATE — do not automate past this point.\n"
        "  1. Present _meta/extractions/{slug}/concept-selection-candidates.md and\n"
        "     concept-selection-rationale-packet.md to the library owner.\n"
        "  2. Write their choices to _meta/extractions/{slug}/phase4-user-selection.json\n"
        "     as {{\"confirmed_slugs\": [...]}}.\n"
        "  3. python3 _meta/scripts/library_phase4_merge_score.py --slug {slug} --confirm "
        "--selection _meta/extractions/{slug}/phase4-user-selection.json"
    ),
    "READY_FOR_5": "python3 _meta/scripts/library_phase5_pages.py --slug {slug}",
    "READY_FOR_POST": (
        "python3 _meta/scripts/library_audit.py --slug {slug} --wiki . "
        "--report _meta/reports/audit-{slug}.json"
    ),
    "DONE": "Nothing. Ingest complete for this slug.",
    "LEGACY_FROZEN": "Nothing. This slug is frozen pre-gate legacy content; do not run phase runners on it.",
}


def inspect(wiki: Path, slug: str) -> dict:
    root = wiki / "_meta" / "extractions" / slug
    state_file = root / "pipeline-state.json"
    out = {"slug": slug, "drift": [], "next": None, "status": None}

    if not state_file.exists():
        out["status"] = "NO_STATE"
        out["next"] = (
            "No pipeline-state.json — this slug has not started (or predates the gate system).\n"
            "  Start: python3 _meta/scripts/library_phase1_ocr.py --slug {slug} "
            '--pdf "$PDF_PATH" --title "$TITLE" --author "$AUTHOR"'
        ).format(slug=slug)
        return out

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt state is drift, not a guess
        out["status"] = "CORRUPT_STATE"
        out["drift"].append(f"pipeline-state.json unreadable: {exc}")
        return out

    status = state.get("status", "")
    out["status"] = status
    out["current_phase"] = state.get("current_phase")
    out["updated_at"] = state.get("updated_at")
    out["runner"] = state.get("runner")

    # Cross-check: recorded values are repository-relative gate paths.
    gates_dir = root / "gates"
    recorded = state.get("gates", {}) or {}
    if not isinstance(recorded, dict):
        out["drift"].append("state gates must be an object of phase -> gate path")
        recorded = {}
    on_disk = {}
    if gates_dir.is_dir():
        for gf in sorted(gates_dir.glob("phase-*.json")):
            try:
                g = json.loads(gf.read_text(encoding="utf-8"))
                phase = gf.stem.replace("phase-", "")
                on_disk[phase] = {"path": gf, "phase": g.get("phase"), "status": g.get("status", "?")}
            except Exception:
                out["drift"].append(f"unreadable gate file: {gf.name}")
    out["gates"] = {phase: gate["status"] for phase, gate in on_disk.items()}
    for phase, path_value in recorded.items():
        try:
            gate_path = (wiki / str(path_value)).resolve()
            gate_path.relative_to(wiki.resolve())
            gate = json.loads(gate_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            out["drift"].append(f"state records missing gate for phase {phase}: {path_value}")
            continue
        except Exception as exc:
            out["drift"].append(f"state gate for phase {phase} is unreadable or unsafe: {path_value}: {exc}")
            continue
        if str(gate.get("phase")) != str(phase):
            out["drift"].append(f"phase {phase}: gate file declares phase {gate.get('phase')!r}")
        if gate.get("status") not in ("PASS", "AWAITING_USER_CONFIRMATION"):
            out["drift"].append(f"phase {phase}: recorded gate status is {gate.get('status')!r}")
        disk = on_disk.get(str(phase))
        if not disk or disk["path"].resolve() != gate_path:
            out["drift"].append(f"phase {phase}: recorded gate path does not match gates/phase-{phase}.json")
    for phase in sorted(set(on_disk) - {str(p) for p in recorded}):
        out["drift"].append(f"unrecorded gate file: gates/phase-{phase}.json")
    bad = [p for p, gate in on_disk.items() if gate["status"] not in ("PASS", "AWAITING_USER_CONFIRMATION")]
    if bad and status not in ("FAILED", "IN_PROGRESS"):
        out["drift"].append(f"non-PASS gate(s) {bad} under a ready status — a phase failed after state advanced")

    if status in NEXT:
        out["next"] = NEXT[status].format(slug=slug)
    elif status == "FAILED":
        out["next"] = (
            f"BLOCKED. Read gates/phase-{state.get('current_phase')}.json and the phase report for the "
            "failure detail, fix the cause, and rerun that phase runner. "
            "See docs/maintainers/domain-library-debugging-playbook. Never edit gate/state files by hand."
        )
    elif status == "IN_PROGRESS":
        out["next"] = (
            "A runner is mid-flight or crashed. If no process is running, read the newest gate/report "
            "JSON to see how far it got, then rerun the current phase runner (they are idempotent "
            "up to their overwrite latches). Do not skip ahead."
        )
    else:
        out["drift"].append(f"unknown status {status!r} — not in the canonical state machine")
    return out


def render(info: dict) -> str:
    lines = [f"slug: {info['slug']}", f"status: {info['status']}"]
    if info.get("updated_at"):
        lines.append(f"updated: {info['updated_at']} by {info.get('runner')}")
    if info.get("gates"):
        lines.append("gates: " + ", ".join(f"{p}={s}" for p, s in sorted(info["gates"].items())))
    for d in info["drift"]:
        lines.append(f"DRIFT: {d}")
    if info["drift"]:
        lines.append("Resolve drift before running anything. Fail closed.")
    if info.get("next") and not info["drift"]:
        lines.append("NEXT:\n  " + info["next"])
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wiki", default=".", help="Library root (default: current directory)")
    ap.add_argument("--slug", help="Book slug to inspect")
    ap.add_argument("--all", action="store_true", help="Inspect every slug under _meta/extractions/")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    args = ap.parse_args()

    wiki = Path(args.wiki).resolve()
    if not (wiki / "_meta").is_dir():
        print(f"error: {wiki} does not look like a library root (no _meta/)", file=sys.stderr)
        return 1
    if not args.slug and not args.all:
        ap.error("--slug or --all required")

    slugs = [validate_slug(args.slug)] if args.slug else sorted(
        p.name for p in (wiki / "_meta" / "extractions").glob("*") if p.is_dir()
    )
    if not slugs:
        print("no extractions found — nothing has been ingested yet")
        return 0

    results = [inspect(wiki, s) for s in slugs]
    if args.json:
        print(json.dumps(results if args.all else results[0], indent=2))
    else:
        print("\n\n".join(render(r) for r in results))
    return 2 if any(r["drift"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
