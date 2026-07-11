#!/usr/bin/env python3
"""Domain Library Phase 2.1/2.2 gated chapter runner.

Phase 2.1 detects chapter boundaries from `book_fidelity.md` or a canonical
`chapter-boundaries.json`. Phase 2.2 writes chapter files, validates extraction
units, and records hard gate/state artifacts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from chapter_splitter import split_chapters
from extraction_units import discover_units

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

RUNNER = "library_phase2_chapters.py"


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def preflight_phase15(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "1.5")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 1.5 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 1.5 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "1.5" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 1.5 complete")
    if state.get("status") not in {"READY_FOR_2.1", "READY_FOR_2", "IN_PROGRESS", "READY_FOR_2.2"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 2.1: {state.get('status')}")
    return state, gate_data


def nonempty_dir(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def remove_existing_output(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def validate_manifest(manifest_path: Path, chapters_dir: Path, slug: str, expected_units: int | None = None) -> dict[str, Any]:
    if not manifest_path.exists() or manifest_path.stat().st_size == 0:
        raise FileNotFoundError(f"manifest not written: {manifest_path}")
    manifest = read_json(manifest_path)
    chapters = manifest.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise RuntimeError(f"manifest has no chapters: {manifest_path}")
    if expected_units is not None and len(chapters) != expected_units:
        raise RuntimeError(f"expected {expected_units} units but manifest has {len(chapters)}")

    missing: list[str] = []
    for ch in chapters:
        if not isinstance(ch, dict):
            raise RuntimeError("manifest chapter entry is not an object")
        file_value = ch.get("file")
        if not isinstance(file_value, str) or not file_value:
            raise RuntimeError("manifest chapter entry missing file")
        path = Path(file_value)
        if not path.is_absolute():
            path = manifest_path.parent / file_value
        if not path.exists():
            missing.append(file_value)
    if missing:
        raise RuntimeError(f"manifest references missing chapter files: {missing}")

    units = discover_units(chapters_dir, slug)
    if not units:
        raise RuntimeError(f"no extraction units discovered in {chapters_dir}")
    if len(units) != len(chapters):
        raise RuntimeError(f"manifest has {len(chapters)} chapters but discovered {len(units)} units")
    return {
        "manifest": manifest,
        "units": [u.__dict__ for u in units],
        "unit_count": len(units),
    }


def parse_expected_units(boundaries_path: Path | None) -> int | None:
    if not boundaries_path or not boundaries_path.exists():
        return None
    data = json.loads(boundaries_path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("expected_units") is not None:
        return int(data["expected_units"])
    if isinstance(data, dict) and isinstance(data.get("chapters"), list):
        return len(data["chapters"])
    return None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 2.1 + 2.2 hard gates")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    ap.add_argument("--boundaries", help="Canonical chapter-boundaries.json; defaults to raw/papers/<slug>/chapter-boundaries.json when present")
    ap.add_argument("--force", action="store_true", help="Replace a non-empty chapters directory")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    raw_root = wiki / "raw" / "papers" / slug
    book_fidelity = raw_root / "book_fidelity.md"
    chapters_dir = raw_root / "chapters"
    manifest_path = raw_root / "manifest.json"
    default_boundaries = raw_root / "chapter-boundaries.json"
    boundaries_path = Path(args.boundaries).resolve() if args.boundaries else (default_boundaries if default_boundaries.exists() else None)

    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state, phase15 = preflight_phase15(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]

        if not book_fidelity.exists() or book_fidelity.stat().st_size == 0:
            raise FileNotFoundError(f"book_fidelity.md missing or empty: {book_fidelity}")
        if nonempty_dir(chapters_dir) and not args.force:
            raise FileExistsError(f"chapters directory is non-empty; rerun with --force to replace: {chapters_dir}")
        if args.force:
            remove_existing_output(chapters_dir)

        expected_units = parse_expected_units(boundaries_path)
        manifest = split_chapters(
            book_fidelity,
            chapters_dir,
            slug,
            boundaries_path,
            manifest_path,
            force=False,
        )
        if manifest["detection_method"] == "fallback-required":
            raise RuntimeError("fallback chunking is forbidden; create chapter-boundaries.json")
        if expected_units is not None and manifest["unit_count"] != expected_units:
            raise RuntimeError(f"expected {expected_units} units but splitter wrote {manifest['unit_count']}")

        phase21_gate = write_gate(
            wiki,
            slug,
            "2.1",
            "PASS",
            {
                "book_fidelity": rel(book_fidelity, wiki),
                "boundaries_file": rel(boundaries_path, wiki) if boundaries_path else "",
                "detection_method": manifest["detection_method"],
                "unit_count": manifest["unit_count"],
                "phase_1_5_gate": phase15,
            },
        )
        gates["2.1"] = rel(phase21_gate, wiki)

        validation = validate_manifest(manifest_path, chapters_dir, slug, expected_units)
        phase22_gate = write_gate(
            wiki,
            slug,
            "2.2",
            "PASS",
            {
                "chapters_dir": rel(chapters_dir, wiki),
                "manifest": rel(manifest_path, wiki),
                "unit_count": validation["unit_count"],
                "units": validation["units"],
            },
        )
        gates["2.2"] = rel(phase22_gate, wiki)
        for phase in ["2.1", "2.2"]:
            if phase not in completed:
                completed.append(phase)
        write_state(wiki, slug, "READY_FOR_2.3", "2.2", completed, gates)
    except Exception as exc:
        phase = "2.1" if "2.1" not in completed else "2.2"
        fail_gate = write_gate(wiki, slug, phase, "FAIL", {"reason": str(exc)})
        gates[phase] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", phase, completed, gates)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "PASS",
                "slug": slug,
                "phase_2_1_gate": gates["2.1"],
                "phase_2_2_gate": gates["2.2"],
                "manifest": rel(manifest_path, wiki),
                "chapters_dir": rel(chapters_dir, wiki),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
