#!/usr/bin/env python3
"""Domain Library Phase 2.4 gated image mapping and verification runner."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from image_chapter_mapper import map_chapter_images
from resolve_ocr_output import resolve as resolve_ocr
from verify_image_refs import verify as verify_image_refs

DEFAULT_WIKI = SCRIPT_DIR.parents[1]


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

RUNNER = "library_phase24_images.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase23(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "2.3")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 2.3 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 2.3 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "2.3" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 2.3 complete")
    if state.get("status") not in {"READY_FOR_2.4", "READY_FOR_3.0", "IN_PROGRESS"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 2.4: {state.get('status')}")
    return state, gate_data


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 2.4 hard image-ref gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    chapters_dir = raw_root / "chapters"
    report_path = raw_root / "image-refs-report.json"
    gates: dict[str, str] = {}
    completed: list[str] = []
    report: dict[str, Any] = {}

    try:
        state, phase23 = preflight_phase23(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        if not chapters_dir.exists():
            raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")

        resolved = resolve_ocr(slug, wiki)
        if resolved["images_dir_required"] and not resolved["images_dir"]:
            raise RuntimeError("OCR JSON has image refs but no local OCR images directory")
        if resolved["images_dir_required"] and resolved["images_dir"] and not any(Path(resolved["images_dir"]).iterdir()):
            raise RuntimeError("OCR JSON has image refs but OCR images directory is empty")

        ocr_json = Path(resolved["json_path"])
        ocr_images_dir = Path(resolved["images_dir"]) if resolved["images_dir"] else None
        mapping = map_chapter_images(chapters_dir, ocr_images_dir, ocr_json)
        verification = verify_image_refs(chapters_dir, forbid_remote=True)
        report = {
            "status": "PASS",
            "slug": slug,
            "generated_at": utc_now(),
            "phase_2_3_gate": phase23,
            "ocr": resolved,
            "mapping": mapping,
            "verification": verification,
        }

        failures: list[str] = []
        if mapping["missing"]:
            failures.append(f"{mapping['missing']} image refs could not be copied/rebased")
        if mapping["remote_refs"]:
            failures.append(f"{mapping['remote_refs']} remote/data image refs remain before verification")
        if verification["missing"]:
            failures.append(f"{verification['missing']} local image refs do not resolve")
        if verification["remote_refs"]:
            failures.append(f"{verification['remote_refs']} remote/data image refs remain")
        if mapping["ocr_image_count"] > 0 and verification["local_refs"] == 0:
            failures.append("OCR output contains images but chapter markdown has zero local image refs")
        if failures:
            report["status"] = "FAIL"
            report["failures"] = failures
            write_json(report_path, report)
            raise RuntimeError("; ".join(failures))

        write_json(report_path, report)
        phase24_gate = write_gate(
            wiki,
            slug,
            "2.4",
            "PASS",
            {
                "chapters_dir": rel(chapters_dir, wiki),
                "report": rel(report_path, wiki),
                "phase_2_3_gate": phase23,
                "ocr_json": rel(ocr_json, wiki),
                "ocr_images_dir": rel(ocr_images_dir, wiki) if ocr_images_dir else "",
                "ocr_image_count": mapping["ocr_image_count"],
                "local_refs": verification["local_refs"],
                "resolved": verification["resolved"],
                "missing": verification["missing"],
                "remote_refs": verification["remote_refs"],
                "copied": mapping["copied"],
                "rewritten": mapping["rewritten"],
                "unreferenced_ocr_images": len(mapping["unreferenced_ocr_images"]),
            },
        )
        gates["2.4"] = rel(phase24_gate, wiki)
        if "2.4" not in completed:
            completed.append("2.4")
        write_state(wiki, slug, "READY_FOR_3.0", "2.4", completed, gates)
    except Exception as exc:
        if report and report.get("status") != "FAIL":
            report["status"] = "FAIL"
            report["failures"] = [str(exc)]
            write_json(report_path, report)
        fail_gate = write_gate(wiki, slug, "2.4", "FAIL", {"reason": str(exc), "report": rel(report_path, wiki) if report_path.exists() else ""})
        gates["2.4"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "2.4", completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_2_4_gate": gates["2.4"],
                "report": rel(report_path, wiki),
                "local_refs": verification["local_refs"],
                "resolved": verification["resolved"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
