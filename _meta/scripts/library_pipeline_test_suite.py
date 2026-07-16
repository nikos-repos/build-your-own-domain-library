#!/usr/bin/env python3
"""Executable smoke tests for proposed Domain Library pipeline architecture."""
from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from domain_library.paths import default_wiki, repository_root
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts import scoring_layer
from _meta.scripts import wiki_integrity
from _meta.scripts import library_phase31_source_index as phase31
from _meta.scripts.extraction_units import discover_units
from _meta.scripts.resolve_ocr_output import resolve
from _meta.scripts.verify_image_refs import verify as verify_images


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    # LIBRARY_SMOKE_RUNNING stops scripts under test (e.g. phase 5's
    # publish hook) from re-invoking this suite recursively.
    env = dict(os.environ, LIBRARY_SMOKE_RUNNING="1")
    root = str(repository_root(Path(__file__)))
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30, env=env)


def test_resolver_api_layout(tmp: Path) -> None:
    root = tmp / "wiki" / "raw" / "papers" / "book-1" / "glmocr_output" / "run1"
    (root / "imgs").mkdir(parents=True)
    (root / "run1.json").write_text(json.dumps([{"image_path": "imgs/a.jpg"}]), encoding="utf-8")
    (root / "run1.md").write_text("hello ![](imgs/a.jpg)", encoding="utf-8")
    (root / "imgs" / "a.jpg").write_bytes(b"x")
    out = resolve("book-1", tmp / "wiki")
    assert out["engine"] == "glm-ocr-api"
    assert out["json_path"].endswith("run1.json")
    assert out["images_dir"].endswith("imgs")


def test_resolver_detects_remote_crop_urls(tmp: Path) -> None:
    root = tmp / "wiki" / "raw" / "papers" / "book-remote" / "glmocr_output"
    root.mkdir(parents=True)
    crop_url = "https://maas-watermark.example/ocr%2Fcrop%2Fabc/crop_1.png?token=x"
    (root / "combined.json").write_text(
        json.dumps(
            {
                "ok": True,
                "text": f"<img src='{crop_url}'/>",
                "layout_details": [[{"label": "image", "content": crop_url, "index": 0}]],
            }
        ),
        encoding="utf-8",
    )
    (root / "book.md").write_text("remote image", encoding="utf-8")
    out = resolve("book-remote", tmp / "wiki")
    assert out["has_image_refs"] is True
    assert out["images_dir_required"] is True
    assert out["images_dir"] == ""


def test_fidelity_requires_local_images(tmp: Path) -> None:
    input_json = tmp / "ocr.json"
    stats_json = tmp / "stats.json"
    input_json.write_text(
        json.dumps(
            {
                "ok": True,
                "text": "image page",
                "layout_details": [[{"label": "image", "native_label": "chart", "index": 0, "content": ""}]],
            }
        ),
        encoding="utf-8",
    )
    proc = run(
        [
            sys.executable,
            str(SCRIPT_DIR / "fidelity_reconstructor.py"),
            "--slug",
            "book-missing-image",
            "--input",
            str(input_json),
            "--output",
            str(tmp / "book_fidelity.md"),
            "--require-images",
            "--stats-json",
            str(stats_json),
        ]
    )
    assert proc.returncode != 0, proc.stdout
    stats = json.loads(stats_json.read_text(encoding="utf-8"))
    assert stats["gate_status"] == "FAIL"
    assert stats["images_missing"] == 1

def seed_phase15_state(wiki: Path, slug: str) -> None:
    gates = wiki / "_meta" / "extractions" / slug / "gates"
    gates.mkdir(parents=True)
    phase15 = gates / "phase-1.5.json"
    phase15.write_text(json.dumps({"phase": "1.5", "status": "PASS", "slug": slug}), encoding="utf-8")
    (wiki / "_meta" / "extractions" / slug / "pipeline-state.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "status": "READY_FOR_2.1",
                "current_phase": "1.5",
                "completed_phases": ["1", "1.5"],
                "gates": {"1.5": str(phase15)},
            }
        ),
        encoding="utf-8",
    )

def seed_phase22_state(wiki: Path, slug: str) -> None:
    gates = wiki / "_meta" / "extractions" / slug / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    phase15 = gates / "phase-1.5.json"
    phase21 = gates / "phase-2.1.json"
    phase22 = gates / "phase-2.2.json"
    phase15.write_text(json.dumps({"phase": "1.5", "status": "PASS", "slug": slug}), encoding="utf-8")
    phase21.write_text(json.dumps({"phase": "2.1", "status": "PASS", "slug": slug}), encoding="utf-8")
    phase22.write_text(json.dumps({"phase": "2.2", "status": "PASS", "slug": slug}), encoding="utf-8")
    (wiki / "_meta" / "extractions" / slug / "pipeline-state.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "status": "READY_FOR_2.3",
                "current_phase": "2.2",
                "completed_phases": ["1", "1.5", "2.1", "2.2"],
                "gates": {"1.5": str(phase15), "2.1": str(phase21), "2.2": str(phase22)},
            }
        ),
        encoding="utf-8",
    )


def write_phase23_fixture(wiki: Path, slug: str, *, wrong_block: bool = False, fallback: bool = False) -> Path:
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    chapters.mkdir(parents=True)
    seed_phase22_state(wiki, slug)
    if fallback:
        chapter_file = chapters / "part-001.md"
        chapter_file.write_text("Fallback paragraph\n", encoding="utf-8")
        manifest_file = "chapters/part-001.md"
        unit_id = "ch00-part001"
    else:
        chapter_file = chapters / "ch-01-concept.md"
        existing = " ^other-book-ch01-0001" if wrong_block else ""
        chapter_file.write_text(
            "---\ntitle: Concept\n---\n# Concept\nConcept paragraph" + existing + "\n| value | meaning |\n|---|---|\n| 1 | beta |\n",
            encoding="utf-8",
        )
        manifest_file = "chapters/ch-01-concept.md"
        unit_id = "ch01"
    (raw / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": slug,
                "unit_count": 1,
                "chapters": [
                    {"chapter": 1, "unit_id": unit_id, "title": "Concept", "file": manifest_file, "source_lines": [1, 4], "lines": 4}
                ],
            }
        ),
        encoding="utf-8",
    )
    return raw

def seed_phase23_state(wiki: Path, slug: str) -> None:
    gates = wiki / "_meta" / "extractions" / slug / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    phase15 = gates / "phase-1.5.json"
    phase21 = gates / "phase-2.1.json"
    phase22 = gates / "phase-2.2.json"
    phase23 = gates / "phase-2.3.json"
    for path, phase in [(phase15, "1.5"), (phase21, "2.1"), (phase22, "2.2"), (phase23, "2.3")]:
        path.write_text(json.dumps({"phase": phase, "status": "PASS", "slug": slug}), encoding="utf-8")
    (wiki / "_meta" / "extractions" / slug / "pipeline-state.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "status": "READY_FOR_2.4",
                "current_phase": "2.3",
                "completed_phases": ["1", "1.5", "2.1", "2.2", "2.3"],
                "gates": {"1.5": str(phase15), "2.1": str(phase21), "2.2": str(phase22), "2.3": str(phase23)},
            }
        ),
        encoding="utf-8",
    )


def write_phase24_fixture(wiki: Path, slug: str, *, remote: bool = False, zero_refs: bool = False) -> Path:
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    ocr = raw / "glmocr_output"
    imgs = ocr / "imgs"
    chapters.mkdir(parents=True)
    imgs.mkdir(parents=True)
    seed_phase23_state(wiki, slug)
    (imgs / "fig-001.png").write_bytes(b"image")
    if remote:
        chapter_text = "# Concept\n![Remote](https://example.com/fig.png) ^{}-ch01-0001\n".format(slug)
    elif zero_refs:
        chapter_text = "# Concept\nNo image refs here. ^{}-ch01-0001\n".format(slug)
    else:
        chapter_text = "# Concept\n![Figure](imgs/fig-001.png) ^{}-ch01-0001\n".format(slug)
    (chapters / "ch-01-concept.md").write_text(chapter_text, encoding="utf-8")
    (raw / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": slug,
                "unit_count": 1,
                "chapters": [{"chapter": 1, "unit_id": "ch01", "title": "Concept", "file": "chapters/ch-01-concept.md"}],
            }
        ),
        encoding="utf-8",
    )
    (ocr / "combined.json").write_text(
        json.dumps(
            {
                "ok": True,
                "text": "![Figure](imgs/fig-001.png)",
                "layout_details": [[{"label": "image", "image_path": "imgs/fig-001.png", "index": 0}]],
            }
        ),
        encoding="utf-8",
    )
    (ocr / "book.md").write_text("![Figure](imgs/fig-001.png)\n", encoding="utf-8")
    return raw

def seed_phase24_state(wiki: Path, slug: str) -> None:
    gates = wiki / "_meta" / "extractions" / slug / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    phase15 = gates / "phase-1.5.json"
    phase21 = gates / "phase-2.1.json"
    phase22 = gates / "phase-2.2.json"
    phase23 = gates / "phase-2.3.json"
    phase24 = gates / "phase-2.4.json"
    for path, phase in [(phase15, "1.5"), (phase21, "2.1"), (phase22, "2.2"), (phase23, "2.3"), (phase24, "2.4")]:
        path.write_text(json.dumps({"phase": phase, "status": "PASS", "slug": slug}), encoding="utf-8")
    (wiki / "_meta" / "extractions" / slug / "pipeline-state.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "status": "READY_FOR_3.0",
                "current_phase": "2.4",
                "completed_phases": ["1", "1.5", "2.1", "2.2", "2.3", "2.4"],
                "gates": {"1.5": str(phase15), "2.1": str(phase21), "2.2": str(phase22), "2.3": str(phase23), "2.4": str(phase24)},
            }
        ),
        encoding="utf-8",
    )


def write_phase30_fixture(wiki: Path, slug: str, *, marker: bool = False, resolved_log: bool = False) -> Path:
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    images = chapters / "images"
    chapters.mkdir(parents=True)
    images.mkdir()
    seed_phase24_state(wiki, slug)
    (images / "fig-001.png").write_bytes(b"image")
    marker_text = " VISION_CHART_NEEDED" if marker else ""
    (chapters / "ch-01-concept.md").write_text(
        f"# Concept\n![Figure](images/fig-001.png){marker_text} ^{slug}-ch01-0001\nConcept text ^{slug}-ch01-0002\n",
        encoding="utf-8",
    )
    if resolved_log:
        out = wiki / "_meta" / "extractions" / slug / "team-ch01"
        out.mkdir(parents=True)
        marker_id = "ch01-L0002-VISION_CHART_NEEDED-1"
        (out / "orchestrator-vision-enrichment.md").write_text(
            "\n".join(
                [
                    f"# Orchestrator Vision Enrichment — {slug} / ch01",
                    "",
                    "status: pass",
                    f"slug: {slug}",
                    "unit_id: ch01",
                    f"chapter_file: {chapters / 'ch-01-concept.md'}",
                    "marker_count: 1",
                    "local_image_ref_count: 1",
                    "",
                    "## Local image refs",
                    "- line 2: `images/fig-001.png` -> `resolved`",
                    "",
                    "## Vision markers",
                    f"### {marker_id}",
                    "status: resolved",
                    f"chapter: {chapters / 'ch-01-concept.md'}",
                    "line: 2",
                    "marker: VISION_CHART_NEEDED",
                    f"block_id: {slug}-ch01-0001",
                    "image_ref: images/fig-001.png",
                    "evidence: The local chart image was inspected and contains a simple line plot.",
                    "patch: Retain existing chapter text; no OCR correction needed.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return raw

def seed_phase30_state(wiki: Path, slug: str) -> None:
    gates = wiki / "_meta" / "extractions" / slug / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    phase15 = gates / "phase-1.5.json"
    phase21 = gates / "phase-2.1.json"
    phase22 = gates / "phase-2.2.json"
    phase23 = gates / "phase-2.3.json"
    phase24 = gates / "phase-2.4.json"
    phase30 = gates / "phase-3.0.json"
    for path, phase in [(phase15, "1.5"), (phase21, "2.1"), (phase22, "2.2"), (phase23, "2.3"), (phase24, "2.4"), (phase30, "3.0")]:
        path.write_text(json.dumps({"phase": phase, "status": "PASS", "slug": slug}), encoding="utf-8")
    (wiki / "_meta" / "extractions" / slug / "pipeline-state.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "status": "READY_FOR_3.1",
                "current_phase": "3.0",
                "completed_phases": ["1", "1.5", "2.1", "2.2", "2.3", "2.4", "3.0"],
                "gates": {"1.5": str(phase15), "2.1": str(phase21), "2.2": str(phase22), "2.3": str(phase23), "2.4": str(phase24), "3.0": str(phase30)},
            }
        ),
        encoding="utf-8",
    )


def write_phase31_fixture(wiki: Path, slug: str, *, wrong_block: bool = False, duplicate: bool = False, split_part: bool = False) -> Path:
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    chapters.mkdir(parents=True)
    seed_phase30_state(wiki, slug)
    team = wiki / "_meta" / "extractions" / slug / ("team-ch08-part02" if split_part else "team-ch01")
    team.mkdir(parents=True)
    (team / "orchestrator-vision-enrichment.md").write_text("status: pass\n## Local image refs\n- none\n", encoding="utf-8")
    if split_part:
        (chapters / "ch-08-risk-part2.md").write_text(
            f"Risk models should not assume stability across regimes. ^{slug}-ch08-0003\n",
            encoding="utf-8",
        )
    elif wrong_block:
        (chapters / "ch-01-concept.md").write_text(
            f"A concept is defined as a named idea. ^other-slug-ch01-0001\n",
            encoding="utf-8",
        )
    elif duplicate:
        (chapters / "ch-01-concept.md").write_text(
            f"A concept is defined as a named idea. ^{slug}-ch01-0001\nDuplicate sentence. ^{slug}-ch01-0001\n",
            encoding="utf-8",
        )
    else:
        (chapters / "ch-01-concept.md").write_text(
            f"A concept is defined as a named idea in a source. ^{slug}-ch01-0001\n"
            f"$x_t = r_t - b_t$ ^{slug}-ch01-0002\n"
            f"However, this estimate is unstable in small samples. ^{slug}-ch01-0003\n",
            encoding="utf-8",
        )
    return raw


def write_phase32_oversize_fixture(wiki: Path, slug: str, *, marker: bool = False, split_part: bool = False) -> Path:
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    chapters.mkdir(parents=True)
    seed_phase30_state(wiki, slug)
    chapter_num = 8 if split_part else 1
    unit_id = "ch08-part02" if split_part else "ch01"
    filename = "ch-08-risk-part2.md" if split_part else "ch-01-concept.md"
    team = wiki / "_meta" / "extractions" / slug / f"team-{unit_id}"
    team.mkdir(parents=True)
    body: list[str] = []
    if marker:
        images = chapters / "images"
        images.mkdir()
        (images / "fig-001.png").write_bytes(b"image")
        body.append(f"![Figure](images/fig-001.png) VISION_CHART_NEEDED ^{slug}-ch{chapter_num:02d}-0001\n")
        marker_id = f"{unit_id}-L0001-VISION_CHART_NEEDED-1"
        (team / "orchestrator-vision-enrichment.md").write_text(
            "\n".join(
                [
                    f"# Orchestrator Vision Enrichment — {slug} / {unit_id}",
                    "",
                    "status: pass",
                    f"slug: {slug}",
                    f"unit_id: {unit_id}",
                    f"chapter_file: {chapters / filename}",
                    "marker_count: 1",
                    "local_image_ref_count: 1",
                    "",
                    "## Local image refs",
                    "- line 1: `images/fig-001.png` -> `resolved`",
                    "",
                    "## Vision markers",
                    f"### {marker_id}",
                    "status: resolved",
                    f"chapter: {chapters / filename}",
                    "line: 1",
                    "marker: VISION_CHART_NEEDED",
                    f"block_id: {slug}-ch{chapter_num:02d}-0001",
                    "image_ref: images/fig-001.png",
                    "evidence: The image was inspected and contains a chart.",
                    "patch: Keep the source text unchanged.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        start = 2
    else:
        (team / "orchestrator-vision-enrichment.md").write_text("status: pass\n## Local image refs\n- none\n", encoding="utf-8")
        start = 1
    for idx in range(start, 46):
        body.append(f"Concept line {idx} defines a useful concept. ^{slug}-ch{chapter_num:02d}-{idx:04d}\n")
    (chapters / filename).write_text("".join(body), encoding="utf-8")
    return raw


def test_phase2_manual_boundaries_write_gates(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase2"
    raw = wiki / "raw" / "papers" / slug
    raw.mkdir(parents=True)
    seed_phase15_state(wiki, slug)
    (raw / "book_fidelity.md").write_text(
        "# Front Matter\nfront\n## 1 Concept\nconcept\n## 2 Beta\nbeta\n",
        encoding="utf-8",
    )
    (raw / "chapter-boundaries.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": slug,
                "expected_units": 3,
                "chapters": [
                    {"chapter": 0, "kind": "frontmatter", "title": "Front Matter", "line_start": 1, "filename": "ch-00-frontmatter.md"},
                    {"chapter": 1, "title": "Concept", "line_start": 3},
                    {"chapter": 2, "title": "Beta", "line_start": 5},
                ],
            }
        ),
        encoding="utf-8",
    )
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase2_chapters.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    manifest = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["detection_method"] == "manual-boundaries"
    assert manifest["unit_count"] == 3
    assert [c["unit_id"] for c in manifest["chapters"]] == ["ch00", "ch01", "ch02"]
    assert (wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.1.json").exists()
    gate22 = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.2.json").read_text(encoding="utf-8"))
    assert gate22["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_2.3"


def test_chapter_splitter_rejects_fallback(tmp: Path) -> None:
    source = tmp / "book_fidelity.md"
    output = tmp / "chapters"
    source.write_text("plain text\nwithout chapter markers\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "chapter_splitter.py"), "--input", str(source), "--output", str(output), "--slug", "fallback-book"])
    assert proc.returncode == 2
    assert not list(output.glob("*.md")) if output.exists() else True


def test_phase2_refuses_existing_chapters(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-existing"
    raw = wiki / "raw" / "papers" / slug
    chapters = raw / "chapters"
    chapters.mkdir(parents=True)
    (chapters / "ch-01-old.md").write_text("old block id ^book-existing-ch01-0001\n", encoding="utf-8")
    seed_phase15_state(wiki, slug)
    (raw / "book_fidelity.md").write_text("# Front Matter\nfront\n## 1 Concept\nconcept\n", encoding="utf-8")
    (raw / "chapter-boundaries.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "slug": slug,
                "expected_units": 2,
                "chapters": [
                    {"chapter": 0, "kind": "frontmatter", "title": "Front Matter", "line_start": 1, "filename": "ch-00-frontmatter.md"},
                    {"chapter": 1, "title": "Concept", "line_start": 3},
                ],
            }
        ),
        encoding="utf-8",
    )
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase2_chapters.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    assert (chapters / "ch-01-old.md").read_text(encoding="utf-8").startswith("old block id")

def test_phase2_recovers_from_detection_failure_and_failed_state(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-recovery"
    raw = wiki / "raw" / "papers" / slug
    raw.mkdir(parents=True)
    seed_phase15_state(wiki, slug)
    (raw / "book_fidelity.md").write_text("Intro para.\n\nBody one.\n\nBody two.\n\nEnd.\n", encoding="utf-8")
    state_file = wiki / "_meta" / "extractions" / slug / "pipeline-state.json"
    runner = str(SCRIPT_DIR / "library_phase2_chapters.py")

    # Article-shaped source: detection failure is an instructive stop, not a FAIL.
    proc = run([sys.executable, runner, "--slug", slug, "--wiki", str(wiki)])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert proc.returncode == 2
    assert state["status"] == "READY_FOR_2.1", state
    assert "chapter-boundaries.json" in proc.stderr

    # A genuine failure (bad boundaries) records FAILED but keeps prior gate records.
    (raw / "chapter-boundaries.json").write_text(
        json.dumps({"expected_units": 3, "chapters": [{"chapter": 1, "title": "Only One", "line_start": 1}]}),
        encoding="utf-8",
    )
    proc = run([sys.executable, runner, "--slug", slug, "--wiki", str(wiki)])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert proc.returncode == 2
    assert state["status"] == "FAILED"
    assert "1.5" in state["gates"], state["gates"]

    # Fixing the cause and rerunning the same phase from FAILED must succeed.
    (raw / "chapter-boundaries.json").write_text(
        json.dumps({
            "expected_units": 2,
            "chapters": [
                {"chapter": 1, "title": "Part One", "line_start": 1},
                {"chapter": 2, "title": "Part Two", "line_start": 3},
            ],
        }),
        encoding="utf-8",
    )
    proc = run([sys.executable, runner, "--slug", slug, "--wiki", str(wiki)])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert state["status"] == "READY_FOR_2.3"

def test_phase23_runner_writes_gate_and_report(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-blocks"
    raw = write_phase23_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase23_blocks.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    text = (raw / "chapters" / "ch-01-concept.md").read_text(encoding="utf-8")
    assert "^book-blocks-ch01-0001" in text
    assert "|---|---| ^book-blocks" not in text
    report = json.loads((raw / "block_annotator-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["total_block_ids"] >= 2
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.3.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_2.4"
    second = run([sys.executable, str(SCRIPT_DIR / "library_phase23_blocks.py"), "--slug", slug, "--wiki", str(wiki)])
    assert second.returncode == 0, second.stderr + second.stdout
    second_report = json.loads((raw / "block_annotator-report.json").read_text(encoding="utf-8"))
    assert second_report["total_added"] == 0


def test_phase23_rejects_wrong_slug_block_ids(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-wrong-blocks"
    raw = write_phase23_fixture(wiki, slug, wrong_block=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase23_blocks.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    assert not (raw / "block_annotator-report.json").exists()
    text = (raw / "chapters" / "ch-01-concept.md").read_text(encoding="utf-8")
    assert "^book-wrong-blocks-ch01-" not in text
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.3.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase23_rejects_fallback_chunks(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-fallback-blocks"
    raw = write_phase23_fixture(wiki, slug, fallback=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase23_blocks.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    assert "^book-fallback-blocks-ch00-" not in (raw / "chapters" / "part-001.md").read_text(encoding="utf-8")

def test_phase24_runner_copies_rewrites_and_gates(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-images"
    raw = write_phase24_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase24_images.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    chapter = raw / "chapters" / "ch-01-concept.md"
    text = chapter.read_text(encoding="utf-8")
    assert "](images/fig-001.png)" in text
    assert (raw / "chapters" / "images" / "fig-001.png").read_bytes() == b"image"
    report = json.loads((raw / "image-refs-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["verification"]["resolved"] == 1
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.0"
    second = run([sys.executable, str(SCRIPT_DIR / "library_phase24_images.py"), "--slug", slug, "--wiki", str(wiki)])
    assert second.returncode == 0, second.stderr + second.stdout
    second_report = json.loads((raw / "image-refs-report.json").read_text(encoding="utf-8"))
    assert second_report["mapping"]["copied"] == 0
    assert second_report["mapping"]["rewritten"] == 0


def test_phase24_rejects_remote_refs(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-remote-images"
    raw = write_phase24_fixture(wiki, slug, remote=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase24_images.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((raw / "image-refs-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["verification"]["remote_refs"] == 1
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-2.4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase24_requires_refs_when_ocr_has_images(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-zero-image-refs"
    raw = write_phase24_fixture(wiki, slug, zero_refs=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase24_images.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((raw / "image-refs-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["mapping"]["ocr_image_count"] == 1
    assert report["verification"]["local_refs"] == 0


def test_phase30_no_markers_writes_pass_logs(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-vision-clean"
    raw = write_phase30_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase30_vision.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    log = wiki / "_meta" / "extractions" / slug / "team-ch01" / "orchestrator-vision-enrichment.md"
    assert log.exists()
    text = log.read_text(encoding="utf-8")
    assert "status: pass" in text
    assert "## Local image refs" in text
    assert "images/fig-001.png" in text
    report = json.loads((raw / "vision-enrichment-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["marker_count"] == 0
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.0.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.1"


def test_phase30_unresolved_marker_fails(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-vision-unresolved"
    raw = write_phase30_fixture(wiki, slug, marker=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase30_vision.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    log = wiki / "_meta" / "extractions" / slug / "team-ch01" / "orchestrator-vision-enrichment.md"
    assert "status: unresolved" in log.read_text(encoding="utf-8")
    report = json.loads((raw / "vision-enrichment-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["marker_count"] == 1
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.0.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase30_accepts_resolved_marker_log(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-vision-resolved"
    raw = write_phase30_fixture(wiki, slug, marker=True, resolved_log=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase30_vision.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads((raw / "vision-enrichment-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["marker_count"] == 1
    assert report["resolved_markers"] == 1
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.1"

def test_phase31_writes_source_index_gate_and_json(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-source-index"
    raw = write_phase31_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    index = wiki / "_meta" / "extractions" / slug / "team-ch01" / "orchestrator-source-index.md"
    text = index.read_text(encoding="utf-8")
    assert "**Total block IDs indexed:** 3" in text
    assert "<!-- source_index_json" in text
    assert "book-source-index-ch01-0001" in text
    assert "book-source-index-ch01-0002" in text
    assert "book-source-index-ch01-0003" in text
    report = json.loads((raw / "source-index-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["total_block_ids"] == 3
    assert report["units"][0]["category_counts"]["Definitions"] == 1
    assert report["units"][0]["category_counts"]["Formulas"] == 1
    assert report["units"][0]["category_counts"]["Warnings / Caveats"] == 1
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.1.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.2"


def test_phase31_classifier_regression(tmp: Path) -> None:
    cases = {
        r"$x_t = r_t - b_t$": "Formulas",
        "import pandas as pd": "Examples / Figures",
        "Market maker: A firm that continuously quotes both sides.": "Definitions",
        "However, this estimate is unstable in small samples.": "Warnings / Caveats",
        "According to prior research, the effect persists.": "Historical / Empirical References",
        "Figure 2 shows the fitted values.": "Examples / Figures",
        "# Methods": "Transitional / Structural",
        "A policy contains rules that govern choices whenever several options remain available to the decision maker.": "Definitions",
    }
    assert {text: phase31.classify(text) for text in cases} == cases
    assert phase31.classify("See [[related-concept]] and [Author, 2020].") != "Formulas"
    assert phase31.classify("This repeatable method remains useful to a decision maker across many ordinary situations.") != "Examples / Figures"


def test_public_layout_entrypoints_resolve(tmp: Path) -> None:
    root = default_wiki()
    doctor = run([sys.executable, str(root / "library.py"), "doctor", "--no-secrets"], cwd=root)
    assert "PASS required files: present" in doctor.stdout
    from _meta.scripts import library_phase1_ocr as phase1
    assert phase1.DEFAULT_GLM_CLI.is_file()
    glm_path = root / "agents" / "orchestrator" / "skills" / "GLM-OCR" / "scripts" / "glm_ocr_cli.py"
    spec = importlib.util.spec_from_file_location("candidate_glm_ocr_cli", glm_path)
    assert spec and spec.loader
    glm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(glm)
    assert glm.ENV_FILE == root / ".env"


def test_installed_command_works_from_a_nested_directory(tmp: Path) -> None:
    command = str(Path(sys.executable).with_name("domain-library"))
    assert Path(command).is_file(), "install the project before running the smoke suite"
    root = repository_root(Path(__file__))
    proc = run([command, "doctor", "--no-secrets"], cwd=root / "_meta")
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_python_support_policy(tmp: Path) -> None:
    import library

    assert library.supported_python((3, 12))
    assert library.supported_python((3, 13))
    assert not library.supported_python((3, 11))


def test_production_code_has_no_path_bootstraps(tmp: Path) -> None:
    root = repository_root(Path(__file__))
    paths = [root / "library.py", *(root / "domain_library").rglob("*.py"), *(root / "_meta" / "scripts").glob("*.py")]
    paths += [
        root / "agents" / "orchestrator" / "skills" / "GLM-OCR" / "scripts" / "glm_ocr_cli.py",
        root / "agents" / "orchestrator" / "skills" / "domain-library-run-and-operate" / "scripts" / "pipeline_next.py",
    ]
    for path in paths:
        if path.name == "library_pipeline_test_suite.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert "sys.path.insert" not in text, path
        assert ".parents[" not in text, path


def test_docs_drift_checker_tracks_live_tree(tmp: Path) -> None:
    root = default_wiki()
    proc = run(["bash", str(root / "_meta" / "scripts" / "docs_drift_check.sh"), str(root)], cwd=root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "catalogued test rows:" in proc.stdout


def test_phase31_rejects_wrong_slug_blocks(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-source-wrong"
    raw = write_phase31_fixture(wiki, slug, wrong_block=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((raw / "source-index-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "wrong-slug" in "\n".join(report["failures"])
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.1.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"

def test_phase31_rejects_duplicate_block_ids(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-source-duplicate"
    raw = write_phase31_fixture(wiki, slug, duplicate=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((raw / "source-index-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "duplicate" in "\n".join(report["failures"])
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.1.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"



def test_phase31_supports_split_part_units(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-source-part"
    raw = write_phase31_fixture(wiki, slug, split_part=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    index = wiki / "_meta" / "extractions" / slug / "team-ch08-part02" / "orchestrator-source-index.md"
    assert index.exists()
    assert f"{slug}-ch08-0003" in index.read_text(encoding="utf-8")
    report = json.loads((raw / "source-index-report.json").read_text(encoding="utf-8"))
    assert report["units"][0]["unit_id"] == "ch08-part02"


def test_phase32_noop_writes_gate(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-size-noop"
    raw = write_phase31_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase32_size_split.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads((raw / "size-split-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["action"] == "no-op"
    assert report["split_count"] == 0
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.2.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.3"


def test_phase32_splits_and_regenerates_indexes(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-size-split"
    raw = write_phase32_oversize_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase32_size_split.py"), "--slug", slug, "--wiki", str(wiki), "--max-lines", "25"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads((raw / "size-split-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["action"] == "split"
    assert report["overlap"] == 0
    assert report["post_unit_count"] > report["pre_unit_count"]
    assert (raw / "chapters" / "ch-01-concept.orig.md").exists()
    assert not (wiki / "_meta" / "extractions" / slug / "team-ch01").exists()
    assert (wiki / "_meta" / "extractions" / slug / "team-ch01-part01" / "orchestrator-source-index.md").exists()
    source_report = json.loads((raw / "source-index-report.json").read_text(encoding="utf-8"))
    assert source_report["status"] == "PASS"
    assert source_report["unique_block_ids"] == 45
    assert all(item["lines"] <= 25 for item in report["units"])
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.3"


def test_phase32_inherits_resolved_vision_markers(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-size-vision"
    raw = write_phase32_oversize_fixture(wiki, slug, marker=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase32_size_split.py"), "--slug", slug, "--wiki", str(wiki), "--max-lines", "25"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    vision_report = json.loads((raw / "vision-enrichment-report.json").read_text(encoding="utf-8"))
    assert vision_report["status"] == "PASS"
    assert vision_report["marker_count"] == 1
    assert vision_report["resolved_markers"] == 1
    inherited = (wiki / "_meta" / "extractions" / slug / "team-ch01-part01" / "orchestrator-vision-enrichment.md").read_text(encoding="utf-8")
    assert "status: resolved" in inherited
    assert "The image was inspected" in inherited


def test_phase32_rejects_nested_oversized_parts(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-size-nested"
    raw = write_phase32_oversize_fixture(wiki, slug, split_part=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase32_size_split.py"), "--slug", slug, "--wiki", str(wiki), "--max-lines", "25"])
    assert proc.returncode == 2
    report = json.loads((raw / "size-split-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "already split units" in "\n".join(report["failures"])
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.2.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def prepare_phase33_fixture(wiki: Path, slug: str) -> Path:
    raw = write_phase31_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase31_source_index.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase32_size_split.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    os.environ.pop("AGENT_PROFILE_DIR", None)
    return raw


def dispatch_result_for_plan(slug: str, plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "slug": slug,
        "tasks": [
            {
                "id": task["id"],
                "job_id": f"runtime-job-{task['id']}",
                "runtime_task_id": f"native-task-{task['id']}",
                "runtime": "test-runtime",
                "model": "test-provider/test-model",
            }
            for task in plan["tasks"]
        ],
    }


def record_phase33_fixture(wiki: Path, slug: str) -> Path:
    raw = prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    write_phase34_outputs(wiki, slug)
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(dispatch_result_for_plan(slug, plan)), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return raw


def write_phase34_outputs(wiki: Path, slug: str, *, omit_lane: str | None = None, invalid_schema_lane: str | None = None) -> None:
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-report.json").read_text(encoding="utf-8"))
    ref = f"raw/papers/{slug}/chapters/ch-01-concept"
    bodies = {
        "defs": f"## Executive Summary\nConcept summary cites ^{slug}-ch01-0001.\n\n## Author's Words\n> \"A concept is defined as a named idea in a source.\"\n\n> \"The excess-return mapping is preserved as a source-grounded formula fixture.\"\n\n— Ch. 1, blocks ^{slug}-ch01-0001 and ^{slug}-ch01-0002\n\n> ![[{ref}#^{slug}-ch01-0001]]\n\n## Rich Definitions\nDefinition analysis cites ^{slug}-ch01-0001.\n",
        "math": f"## Author's Formulation\n$$x_t = r_t - b_t$$\n— block ^{slug}-ch01-0002\n> ![[{ref}#^{slug}-ch01-0002]]\n",
        "examples": f"## Specific Example\nThe benchmark excess-return example cites ^{slug}-ch01-0001.\n\n## Figures and Diagrams\nNo explicit figures are given by the authors in this chapter; see ^{slug}-ch01-0001.\n\n## Implementation Details\nNo explicit implementation details are given by the authors in this chapter; see ^{slug}-ch01-0002.\n",
        "warnings": f"## Author's Warnings\n### 1. Small Sample Instability [Sensitivity: High]\n> \"However, this estimate is unstable in small samples.\"\n— block ^{slug}-ch01-0003\n\n## Limitations and Counter-Arguments\nThe formula boundary is unstable in small samples; see ^{slug}-ch01-0003.\n",
        "context": f"## Historical / Empirical Context\n- No explicit named historical references are given; closest evidence is ^{slug}-ch01-0001.\n\n## Calibration Data Sources\n| Parameter | Empirical Source | Data Type | Key Finding |\n|---|---|---|---|\n| x_t | source block ^{slug}-ch01-0002 | formula | excess return mapping |\n\n## Relations\n- extracted_from::[[{ref}#^{slug}-ch01-0001]]\n  - Concept comes from the source definition.\n- informed_by::[[{ref}#^{slug}-ch01-0002]]\n  - Formula context informs the node.\n- validated_by::[[{ref}#^{slug}-ch01-0003]]\n  - Caveat constrains confidence.\n",
    }
    for task in report["tasks"]:
        lane = task["lane"]
        if lane == omit_lane:
            (wiki / task["markdown_output"]).unlink(missing_ok=True)
            (wiki / task["schema_output"]).unlink(missing_ok=True)
            continue
        md = wiki / task["markdown_output"]
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(bodies[lane], encoding="utf-8")
        schema = wiki / task["schema_output"]
        schema.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "source": slug,
            "chapter": 1,
            "chapter_title": "Concept",
            "extracted_at": "2026-06-08T00:00:00+00:00",
            "concepts": [
                {
                    "slug": f"{lane}-concept",
                    "name": f"{lane} concept",
                    "definitions": [
                        {
                            "chapter": 1,
                            "chapter_title": "Concept",
                            "definition": "Concept is defined as source-grounded a named idea in a source in this test fixture.",
                            "block_id": f"{slug}-ch01-0001",
                        }
                    ],
                    "examples": [],
                    "warnings": [],
                    "formulas": [],
                    "block_ids": [f"{slug}-ch01-0001"],
                    "cross_references": [],
                    "confidence": 0.7,
                    "concepts_per_100_lines": 1.0,
                    "chapters": [1],
                }
            ],
            "entities": [],
            "formulas": [],
            "claims": [],
        }
        if lane == invalid_schema_lane:
            data["concepts"][0]["definitions"][0]["definition"] = "short"
        schema.write_text(json.dumps(data), encoding="utf-8")


def pass_phase34_fixture(wiki: Path, slug: str) -> Path:
    raw = record_phase33_fixture(wiki, slug)
    write_phase34_outputs(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase34_verify.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return raw


def test_phase33_prepare_writes_dispatch_payload(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-prepare"
    prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    assert plan["status"] == "READY_FOR_DISPATCH"
    assert plan["dispatch_model"] == "runtime-native-subagents"
    assert plan["agent_mode"] == "runtime-neutral-prompt-contracts"
    assert plan["agents"] == ["defs", "math", "examples", "warnings", "context"]
    assert set(plan["agent_profiles"]) == set(plan["agents"])
    assert "task_tool_payload" not in plan
    first_invocation = plan["chapter_task_payload_batches"][0]["agent_invocations"][0]
    assert first_invocation["profile"] == "domain-defs/defs.md"
    assert len(first_invocation["expected_outputs"]) == 2
    assert plan["task_count"] == 5
    assert {task["lane"] for task in plan["tasks"]} == {"defs", "math", "examples", "warnings", "context"}
    assert {task["agent_type"] for task in plan["tasks"]} == {"defs", "math", "examples", "warnings", "context"}
    assert all("Lane prompt" not in task["assignment"] for task in plan["tasks"])
    assert all("Named lane worker profile" in task["assignment"] for task in plan["tasks"])
    assert all("Schema JSON draft output" in task["assignment"] for task in plan["tasks"])
    assert all("Block embeds must be exactly" in task["assignment"] for task in plan["tasks"])
    assert all("relates_to::" in task["assignment"] for task in plan["tasks"])
    assert all("related_to::" in task["assignment"] for task in plan["tasks"])
    assert all("never use" in task["assignment"].split("# Evidence hygiene", 1)[1] for task in plan["tasks"])
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "IN_PROGRESS"
    assert not (wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.3.json").exists()


def test_phase33_prepare_rejects_missing_native_agent(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-missing-agent"
    prepare_phase33_fixture(wiki, slug)
    agent_dir = wiki.parent / "lane-agents"
    workers = default_wiki() / "agents" / "library-workers"
    for profile in workers.rglob("*.md"):
        dest = agent_dir / profile.relative_to(workers)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(profile.read_text(encoding="utf-8"), encoding="utf-8")
    os.environ["AGENT_PROFILE_DIR"] = str(agent_dir)
    (agent_dir / "domain-math" / "math.md").unlink()
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 2
    assert "agent profile for math missing or empty" in proc.stderr
    os.environ.pop("AGENT_PROFILE_DIR", None)


def test_phase33_record_writes_gate_after_jobs_recorded(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-record"
    prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan_path = wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    write_phase34_outputs(wiki, slug)
    result = dispatch_result_for_plan(slug, plan)
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["agent_mode"] == "runtime-neutral-prompt-contracts"
    assert report["tasks"][0]["agent_type"] == "defs"
    assert report["tasks"][0]["runtime"] == "test-runtime"
    assert report["tasks"][0]["model"] == "test-provider/test-model"
    assert report["task_count"] == 5
    assert report["task_ids"]["ch01"]["defs"].startswith("native-task-")
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.3.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.4"

def test_phase33_record_accepts_alternate_runtime_shape(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-no-canary"
    prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    result = dispatch_result_for_plan(slug, plan)
    write_phase34_outputs(wiki, slug)
    result = {"slug": slug, "results": [{"id": item["id"], "run_id": item["job_id"], "task_id": item["runtime_task_id"], "launcher": item["runtime"], "model_id": item["model"]} for item in result["tasks"]]}
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 0, proc.stderr + proc.stdout



def test_phase33_record_rejects_synthetic_job_ids(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-synthetic"
    prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    result = dispatch_result_for_plan(slug, plan)
    write_phase34_outputs(wiki, slug)
    first = result["tasks"][0]
    first["job_id"] = f"fake-{first['id']}"
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 2
    assert "synthetic identifier" in proc.stderr



def test_phase33_record_rejects_missing_job_ids(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-missing"
    prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    result = dispatch_result_for_plan(slug, plan)
    write_phase34_outputs(wiki, slug)
    result["tasks"] = result["tasks"][:-1]
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 2
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.3.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_pipeline_manifest_consumes_runtime_dispatch(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dispatch-manifest"
    raw = prepare_phase33_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--prepare"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    plan = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-dispatch-plan.json").read_text(encoding="utf-8"))
    write_phase34_outputs(wiki, slug)
    result_path = wiki / "_meta" / "extractions" / slug / "dispatch-result.json"
    result_path.write_text(json.dumps(dispatch_result_for_plan(slug, plan)), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase33_dispatch.py"), "--slug", slug, "--wiki", str(wiki), "--record", "--dispatch-result", str(result_path)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    manifest_path = wiki / "_meta" / "extractions" / slug / "pipeline-run-manifest.json"
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "pipeline_run_manifest.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--chapters-dir",
        str(raw / "chapters"),
        "--specialist-dispatch-report",
        str(wiki / "_meta" / "extractions" / slug / "specialist-dispatch-report.json"),
        "--output",
        str(manifest_path),
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["dispatch_model"] == "runtime-native-subagents"
    specialist_tasks = [task for task in manifest["tasks"] if task["owner"] == "specialist"]
    assert len(specialist_tasks) == 5
    assert all(str(task["task_id"]).startswith("native-task-") for task in specialist_tasks)
    assert all(task["schema_output"]["path"].endswith(".json") for task in specialist_tasks)


def test_phase34_verifies_outputs_schema_and_manifest(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-verify-pass"
    record_phase33_fixture(wiki, slug)
    write_phase34_outputs(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase34_verify.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-verification.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["checked"] == 5
    schema_report = json.loads((wiki / "_meta" / "extractions" / slug / "schema-validation-report.json").read_text(encoding="utf-8"))
    assert schema_report["status"] == "PASS"
    assert (wiki / "_meta" / "extractions" / slug / "_validation_passed").exists()
    manifest = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["dispatch_model"] == "runtime-native-subagents"
    assert manifest["verification"]["specialist_verifier_status"] == "PASS"
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_3.5"
    assert not (wiki / "_meta" / "extractions" / slug / "team-ch01" / "team-ch01-presentation.md").exists()


def test_phase34_rejects_missing_markdown_output(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-verify-missing"
    record_phase33_fixture(wiki, slug)
    write_phase34_outputs(wiki, slug, omit_lane="math")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase34_verify.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-verification.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "missing markdown output" in "\n".join(report["failures"])
    assert not (wiki / "_meta" / "extractions" / slug / "_validation_passed").exists()
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase34_rejects_invalid_schema_output(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-verify-schema"
    record_phase33_fixture(wiki, slug)
    write_phase34_outputs(wiki, slug, invalid_schema_lane="defs")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase34_verify.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    schema_report = json.loads((wiki / "_meta" / "extractions" / slug / "schema-validation-report.json").read_text(encoding="utf-8"))
    assert schema_report["status"] == "FAIL"
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-verification.json").read_text(encoding="utf-8"))
    assert "extraction_schema.py validation failed" in "\n".join(report["failures"])


def test_phase34_rejects_evidence_hygiene_defects(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-verify-evidence"
    record_phase33_fixture(wiki, slug)
    write_phase34_outputs(wiki, slug)
    qcontext = wiki / "_meta" / "extractions" / slug / "team-ch01" / "domain-empirical-context.md"
    qcontext.write_text(qcontext.read_text(encoding="utf-8") + f"\n- related_to::[[concept]]\n- extracted_from::[[{slug}]]\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase34_verify.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "specialist-verification.json").read_text(encoding="utf-8"))
    failures = "\n".join(report["failures"])
    assert "evidence hygiene violation" in failures
    assert "use relates_to::, not related_to::" in failures
    assert "block evidence predicate without #^ anchor" in failures


def test_phase35_assembles_and_gates_presentations(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-present-pass"
    pass_phase34_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase35_presentations.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    presentation = wiki / "_meta" / "extractions" / slug / "team-ch01" / "team-ch01-presentation.md"
    text = presentation.read_text(encoding="utf-8")
    assert "## Author's Words" in text
    assert "## Relations" in text
    report = json.loads((wiki / "_meta" / "extractions" / slug / "presentation-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["checked"] == 1
    assert report["presentations"][0]["block_embed_count"] >= 2
    assert report["presentations"][0]["author_quote_lines"] >= 2
    audit_json = wiki / "_meta" / "extractions" / slug / "presentation-evidence-balance-audit.json"
    audit_md = wiki / "_meta" / "extractions" / slug / "presentation-evidence-balance-audit.md"
    assert audit_json.exists()
    assert audit_md.exists()
    assert report["evidence_balance_audit"].endswith("presentation-evidence-balance-audit.json")
    assert report["evidence_balance_markdown"].endswith("presentation-evidence-balance-audit.md")
    assert report["evidence_balance_status"] in {"PASS", "WARN"}
    audit = json.loads(audit_json.read_text(encoding="utf-8"))
    assert audit["lesson_candidate"] == "L-009"
    assert audit["scope"] == "post_phase_3_5_presentation_evidence_balance_audit"
    assert audit["unit_count"] == 1
    assert "evidence_index" in audit["required_categories"]
    assert "relations" in audit["required_categories"]
    assert "categories" in audit["units"][0]
    manifest = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-run-manifest.json").read_text(encoding="utf-8"))
    assert manifest["presentation_summary"]["status"] == "PASS"
    assert manifest["presentations"][0]["output"].endswith("team-ch01-presentation.md")
    assert manifest["source_reports"]["presentation_evidence_balance_audit"].endswith("presentation-evidence-balance-audit.json")
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.5.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    assert gate["evidence_balance_audit"].endswith("presentation-evidence-balance-audit.json")
    state = json.loads((wiki / "_meta" / "extractions" / slug / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_4"


def test_phase35_rejects_missing_presentation_section(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-present-missing"
    pass_phase34_fixture(wiki, slug)
    qmath = wiki / "_meta" / "extractions" / slug / "team-ch01" / "domain-math.md"
    qmath.write_text(f"## Different Header\nStill cites ^{slug}-ch01-0002.\n> ![[raw/papers/{slug}/chapters/ch-01-concept#^{slug}-ch01-0002]]\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase35_presentations.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "presentation-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "missing required presentation sections" in "\n".join(report["failures"])
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-3.5.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase35_rejects_insufficient_author_quotes(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-present-quotes"
    pass_phase34_fixture(wiki, slug)
    qdefs = wiki / "_meta" / "extractions" / slug / "team-ch01" / "domain-definitions.md"
    qdefs.write_text(f"## Executive Summary\nConcept summary cites ^{slug}-ch01-0001.\n\n## Author's Words\n> \"A concept is defined as a named idea in a source.\"\n\n— Ch. 1, block ^{slug}-ch01-0001\n\n> ![[raw/papers/{slug}/chapters/ch-01-concept#^{slug}-ch01-0001]]\n\n## Rich Definitions\nDefinition analysis cites ^{slug}-ch01-0001.\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase35_presentations.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "presentation-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "Author's Words has 1 substantial quote lines" in "\n".join(report["failures"])


def pass_phase35_fixture(wiki: Path, slug: str) -> Path:
    raw = pass_phase34_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase35_presentations.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return raw


def inject_source_index_comment_marker(wiki: Path, slug: str) -> None:
    """Regression fixture: source-index block text may contain literal `-->`."""
    index_path = wiki / "_meta" / "extractions" / slug / "team-ch01" / "orchestrator-source-index.md"
    text = index_path.read_text(encoding="utf-8")
    marker = "<!-- source_index_json"
    start = text.find(marker)
    end = text.rfind("-->")
    assert start >= 0 and end > start
    payload = json.loads(text[start + len(marker):end].strip())
    payload["blocks"][0]["text"] = "Concept text may contain a literal --> marker from OCR comments."
    index_path.write_text(text[: start + len(marker)] + "\n" + json.dumps(payload, ensure_ascii=False) + "\n" + text[end:], encoding="utf-8")




def test_phase4_prepare_scores_filters_and_awaits_confirmation(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase4-prepare"
    pass_phase35_fixture(wiki, slug)
    inject_source_index_comment_marker(wiki, slug)
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--prepare",
        "--min-score",
        "3",
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    root = wiki / "_meta" / "extractions" / slug
    report = json.loads((root / "phase4-scoring-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "AWAITING_USER_CONFIRMATION"
    assert report["candidate_count"] == 5
    assert (root / "master-scored.json").exists()
    assert (root / "master-top-clean.json").exists()
    assert (root / "concept-selection-candidates.md").exists()
    assert (root / "concept-selection-rationale-packet.json").exists()
    assert (root / "concept-selection-rationale-packet.md").exists()
    candidates = json.loads((root / "concept-selection-candidates.json").read_text(encoding="utf-8"))
    rationale = json.loads((root / "concept-selection-rationale-packet.json").read_text(encoding="utf-8"))
    assert candidates["rationale_packet_json"] == f"_meta/extractions/{slug}/concept-selection-rationale-packet.json"
    assert report["rationale_packet_json"] == f"_meta/extractions/{slug}/concept-selection-rationale-packet.json"
    assert rationale["lesson_candidate"] == "L-010"
    assert rationale["rationale_count"] == report["total_scored_concepts"]
    assert len(rationale["rationales"]) == report["total_scored_concepts"]
    assert {row["status"] for row in rationale["rationales"]} == {"included"}
    assert all(row["strongest_block_ids"] for row in rationale["rationales"])
    block_report = json.loads((root / "blockid-validation-report.json").read_text(encoding="utf-8"))
    assert block_report["valid"] is True
    assert (root / "_blockid_valid").exists()
    gate = json.loads((root / "gates" / "phase-4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "AWAITING_USER_CONFIRMATION"
    state = json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "AWAITING_USER_CONFIRMATION"


def test_phase4_confirm_writes_pass_gate(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase4-confirm"
    pass_phase35_fixture(wiki, slug)
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--prepare",
        "--min-score",
        "3",
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    root = wiki / "_meta" / "extractions" / slug
    selection = root / "phase4-user-selection.json"
    selection.write_text(json.dumps({"confirmed_slugs": ["defs-concept", "math-concept"]}), encoding="utf-8")
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--confirm",
        "--selection",
        str(selection),
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    confirmation = json.loads((root / "phase4-confirmation.json").read_text(encoding="utf-8"))
    assert confirmation["status"] == "PASS"
    assert confirmation["selected_count"] == 2
    assert set(confirmation["concepts"]) == {"defs-concept", "math-concept"}
    gate = json.loads((root / "gates" / "phase-4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_5"


def test_phase4_rejects_dead_block_ids(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase4-dead-block"
    pass_phase35_fixture(wiki, slug)
    schema_file = wiki / "_meta" / "extractions" / slug / "schema" / "ch01-defs.json"
    data = json.loads(schema_file.read_text(encoding="utf-8"))
    data["concepts"][0]["block_ids"] = [f"{slug}-ch01-9999"]
    data["concepts"][0]["definitions"][0]["block_id"] = f"{slug}-ch01-9999"
    schema_file.write_text(json.dumps(data), encoding="utf-8")
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--prepare",
        "--min-score",
        "3",
    ])
    assert proc.returncode == 2
    block_report = json.loads((wiki / "_meta" / "extractions" / slug / "blockid-validation-report.json").read_text(encoding="utf-8"))
    assert block_report["valid"] is False
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-4.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def pass_phase4_fixture(wiki: Path, slug: str, selected: list[str] | None = None) -> Path:
    raw = pass_phase35_fixture(wiki, slug)
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--prepare",
        "--min-score",
        "3",
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    root = wiki / "_meta" / "extractions" / slug
    selection = root / "phase4-user-selection.json"
    selection.write_text(json.dumps({"confirmed_slugs": selected or ["defs-concept", "math-concept"]}), encoding="utf-8")
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--confirm",
        "--selection",
        str(selection),
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return raw


def test_cli_run_executes_phase4_and_phase5_runners(tmp: Path) -> None:
    # Regression: `domain-library run` executes runners as `python -m`, where a
    # bare sibling import crashes even though direct-path invocation works.
    wiki = tmp / "wiki"
    slug = "book-cli-run"
    pass_phase35_fixture(wiki, slug)
    library = str(repository_root(Path(__file__)) / "library.py")
    proc = run([
        sys.executable, library, "run", "library_phase4_merge_score",
        "--slug", slug, "--wiki", str(wiki), "--prepare", "--min-score", "3",
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    root = wiki / "_meta" / "extractions" / slug
    selection = root / "phase4-user-selection.json"
    selection.write_text(json.dumps({"confirmed_slugs": ["defs-concept"]}), encoding="utf-8")
    proc = run([
        sys.executable, library, "run", "library_phase4_merge_score",
        "--slug", slug, "--wiki", str(wiki), "--confirm", "--selection", str(selection),
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([
        sys.executable, library, "run", "library_phase5_pages",
        "--slug", slug, "--wiki", str(wiki),
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert (wiki / "concepts" / "defs-concept.md").exists()

def test_phase5_writes_pages_from_team_presentations(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase5-pass"
    pass_phase4_fixture(wiki, slug)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase5_pages.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    root = wiki / "_meta" / "extractions" / slug
    report = json.loads((root / "page-build-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["pages_written"] == 2
    page = wiki / "concepts" / "defs-concept.md"
    text = page.read_text(encoding="utf-8")
    assert "quality_notes:" in text
    assert "## Author's Words" in text
    assert "## Source-grounded definition" in text
    assert "## Specific Example" in text
    assert "## Evidence index" in text
    assert "extracted_from::" in text
    assert "derived_from::" not in text
    assert text.count("![[") >= 2
    assert len(text.splitlines()) >= 80
    assert "[[defs-concept]]" in (wiki / "index.md").read_text(encoding="utf-8")
    assert slug in (wiki / "log.md").read_text(encoding="utf-8")
    gate = json.loads((root / "gates" / "phase-5.json").read_text(encoding="utf-8"))
    assert gate["status"] == "PASS"
    state = json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "READY_FOR_POST"


def test_phase5_requires_phase4_confirmation_pass(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase5-no-confirm"
    pass_phase35_fixture(wiki, slug)
    proc = run([
        sys.executable,
        str(SCRIPT_DIR / "library_phase4_merge_score.py"),
        "--slug",
        slug,
        "--wiki",
        str(wiki),
        "--prepare",
        "--min-score",
        "3",
    ])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase5_pages.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    gate = json.loads((wiki / "_meta" / "extractions" / slug / "gates" / "phase-5.json").read_text(encoding="utf-8"))
    assert gate["status"] == "FAIL"


def test_phase5_rejects_existing_page_without_force(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-phase5-existing"
    pass_phase4_fixture(wiki, slug, selected=["defs-concept"])
    concepts = wiki / "concepts"
    concepts.mkdir(exist_ok=True)
    (concepts / "defs-concept.md").write_text("existing page\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase5_pages.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "page-build-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "page already exists" in "\n".join(report["failures"])




def test_units_do_not_collapse_parts(tmp: Path) -> None:
    ch = tmp / "chapters"; ch.mkdir()
    for name in ["ch-08-risk.md", "ch-08-risk-part2.md", "part-001.md"]:
        (ch / name).write_text("text\n", encoding="utf-8")
    ids = [u.unit_id for u in discover_units(ch, "slug")]
    assert ids == ["ch00-part001", "ch08", "ch08-part02"] or ids == ["ch08", "ch08-part02", "ch00-part001"]
    assert len(ids) == len(set(ids))


def test_block_annotator_scans_fallback_chunks(tmp: Path) -> None:
    ch = tmp / "chapters"; ch.mkdir()
    (ch / "part-001.md").write_text("# Fallback\n\nConcept paragraph\nBeta paragraph\n", encoding="utf-8")
    (ch / "part-002.md").write_text("Gamma paragraph\n", encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "block_annotator.py"), "--input-dir", str(ch), "--slug", "slug", "--json"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(ch.glob("*.md")))
    assert "^slug-ch00-0001" in text
    assert "^slug-ch00-0003" in text


def test_image_verifier_detects_missing(tmp: Path) -> None:
    ch = tmp / "chapters"; ch.mkdir()
    (ch / "ch-01.md").write_text("ok ![](images/a.png) bad ![](images/missing.png)\n", encoding="utf-8")
    (ch / "images").mkdir()
    (ch / "images" / "a.png").write_bytes(b"x")
    out = verify_images(ch)
    assert out["resolved"] == 1
    assert out["missing"] == 1


def test_scoring_folds_plural_and_possessive_slug_variants(tmp: Path) -> None:
    extractions = [
        {
            "chapter": 1,
            "concepts": [
                {"slug": "gambler-s-ruin", "name": "Gambler's Ruin", "definitions": [{"d": 1}], "block_ids": ["b-ch01-0001"], "confidence": 0.7},
                {"slug": "arc-sine-laws", "name": "Arc Sine Laws", "examples": [{"e": 1}], "block_ids": ["b-ch01-0002"], "confidence": 0.6},
            ],
        },
        {
            "chapter": 2,
            "concepts": [
                {"slug": "gambler-ruin", "name": "Gambler's Ruin", "warnings": [{"w": 1}], "block_ids": ["b-ch02-0001"], "confidence": 0.9},
                {"slug": "arc-sine-law", "name": "Arc Sine Law", "definitions": [{"d": 2}], "block_ids": ["b-ch02-0002"], "confidence": 0.8},
            ],
        },
    ]
    merged = scoring_layer.merge_concepts(extractions)
    assert "gambler-ruin" in merged and "gambler-s-ruin" not in merged
    assert "arc-sine-law" in merged and "arc-sine-laws" not in merged
    ruin = merged["gambler-ruin"]
    assert ruin["merged_slugs"] == ["gambler-ruin", "gambler-s-ruin"]
    assert ruin["confidence"] == 0.9
    assert set(ruin["block_ids"]) == {"b-ch01-0001", "b-ch02-0001"}


def test_phase4_flags_duplicates_and_confirm_refuses(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-dedup"
    pass_phase35_fixture(wiki, slug)
    schema = wiki / "_meta" / "extractions" / slug / "schema"
    base = json.loads((schema / "ch01-defs.json").read_text(encoding="utf-8"))
    twin = dict(base)
    twin_concepts = []
    for concept in base.get("concepts", []):
        c = dict(concept)
        c["slug"] = "defs-concept-rate"
        c["name"] = "Defs Concept Rate"
        twin_concepts.append(c)
    twin["concepts"] = twin_concepts
    (schema / "ch01-defs-twin.json").write_text(json.dumps(twin), encoding="utf-8")
    (wiki / "concepts").mkdir(parents=True, exist_ok=True)
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase4_merge_score.py"), "--slug", slug, "--wiki", str(wiki), "--prepare", "--min-score", "0"])
    assert proc.returncode == 0, proc.stderr + proc.stdout
    candidates = json.loads((wiki / "_meta" / "extractions" / slug / "concept-selection-candidates.json").read_text(encoding="utf-8"))
    flagged_pairs = [set(f["slugs"]) for f in candidates["duplicate_flags"] if f["kind"] == "in-batch"]
    assert any({"defs-concept", "defs-concept-rate"} == pair for pair in flagged_pairs), candidates["duplicate_flags"]
    selection = wiki / "_meta" / "extractions" / slug / "phase4-user-selection.json"
    selection.write_text(json.dumps({"confirmed_slugs": ["defs-concept", "defs-concept-rate"]}), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase4_merge_score.py"), "--slug", slug, "--wiki", str(wiki), "--confirm", "--selection", str(selection)])
    assert proc.returncode == 2
    assert "duplicate-flagged" in proc.stderr
    selection.write_text(json.dumps({"confirmed_slugs": ["defs-concept"]}), encoding="utf-8")
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase4_merge_score.py"), "--slug", slug, "--wiki", str(wiki), "--confirm", "--selection", str(selection)])
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_phase35_rejects_dead_embed_target(tmp: Path) -> None:
    wiki = tmp / "wiki"
    slug = "book-present-deadlink"
    pass_phase34_fixture(wiki, slug)
    qmath = wiki / "_meta" / "extractions" / slug / "team-ch01" / "domain-math.md"
    qmath.write_text(
        f"## Author's Formulation\n$$x_t = r_t - b_t$$\n— block ^{slug}-ch01-0002\n> ![[source#^{slug}-ch01-0002]]\n",
        encoding="utf-8",
    )
    proc = run([sys.executable, str(SCRIPT_DIR / "library_phase35_presentations.py"), "--slug", slug, "--wiki", str(wiki)])
    assert proc.returncode == 2
    report = json.loads((wiki / "_meta" / "extractions" / slug / "presentation-report.json").read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert "unresolvable/non-canonical block links" in "\n".join(report["failures"])


def integrity_fixture(tmp: Path) -> Path:
    wiki = tmp / "wiki"
    chapters = wiki / "raw" / "papers" / "book-x" / "chapters"
    chapters.mkdir(parents=True)
    (chapters / "ch-01-intro.md").write_text("Concept line. ^book-x-ch01-0001\nBeta line. ^book-x-ch01-0002\n", encoding="utf-8")
    (wiki / "concepts").mkdir(parents=True)
    return wiki


def test_integrity_resolves_ok_and_anchor_missing(tmp: Path) -> None:
    wiki = integrity_fixture(tmp)
    page = wiki / "concepts" / "concept.md"
    page.write_text(
        "![[raw/papers/book-x/chapters/ch-01-intro#^book-x-ch01-0001]]\n"
        "![[raw/papers/book-x/chapters/ch-01-intro#^book-x-ch01-9999]]\n",
        encoding="utf-8",
    )
    index = wiki_integrity.build_vault_index(wiki)
    findings = wiki_integrity.check_text(index, page.read_text(encoding="utf-8"))
    assert [f["status"] for f in findings] == ["ok", "anchor_missing"]
    assert findings[0]["resolved_path"] == "raw/papers/book-x/chapters/ch-01-intro"


def test_integrity_detects_target_missing_and_ambiguous(tmp: Path) -> None:
    wiki = integrity_fixture(tmp)
    other = wiki / "raw" / "papers" / "book-y" / "chapters"
    other.mkdir(parents=True)
    (other / "ch-01-intro.md").write_text("Gamma. ^book-y-ch01-0001\n", encoding="utf-8")
    index = wiki_integrity.build_vault_index(wiki)
    findings = wiki_integrity.check_text(
        index,
        "![[source#^book-x-ch01-0001]]\n![[ch-01-intro#^book-x-ch01-0001]]\n",
    )
    assert [f["status"] for f in findings] == ["target_missing", "target_ambiguous"]


def test_integrity_detects_malformed_forms(tmp: Path) -> None:
    wiki = integrity_fixture(tmp)
    index = wiki_integrity.build_vault_index(wiki)
    findings = wiki_integrity.check_text(
        index,
        "![[source#^[book-x-ch01-0001]]]\n![[book-x-ch01-0002]]\n",
    )
    statuses = {f["status"] for f in findings}
    assert statuses == {"malformed_bracket_anchor", "malformed_anchorless_id"}


def test_integrity_suffix_match_and_basename(tmp: Path) -> None:
    wiki = integrity_fixture(tmp)
    index = wiki_integrity.build_vault_index(wiki)
    findings = wiki_integrity.check_text(
        index,
        "![[book-x/chapters/ch-01-intro#^book-x-ch01-0001]]\n"
        "[[ch-01-intro#^book-x-ch01-0002|^ch01-0002]]\n",
    )
    assert [f["status"] for f in findings] == ["suffix_match", "ok"]
    assert findings[1]["embed"] is False


def write_runner_state(wiki: Path, slug: str, *, status: str = "READY_FOR_2.3", gate_phase: str = "2.2", declared_phase: str | None = None) -> Path:
    root = wiki / "_meta" / "extractions" / slug
    gate = root / "gates" / f"phase-{gate_phase}.json"
    gate.parent.mkdir(parents=True)
    gate.write_text(json.dumps({"phase": declared_phase or gate_phase, "status": "PASS", "slug": slug}), encoding="utf-8")
    (root / "pipeline-state.json").write_text(json.dumps({"slug": slug, "status": status, "current_phase": gate_phase, "completed_phases": [gate_phase], "gates": {gate_phase: str(gate.relative_to(wiki))}}), encoding="utf-8")
    return gate


def run_pipeline_next(wiki: Path, slug: str) -> subprocess.CompletedProcess:
    script = default_wiki() / "agents" / "orchestrator" / "skills" / "domain-library-run-and-operate" / "scripts" / "pipeline_next.py"
    return run([sys.executable, str(script), "--wiki", str(wiki), "--slug", slug])


def test_pipeline_next_accepts_real_gate_paths(tmp: Path) -> None:
    wiki = tmp / "wiki"
    gate = write_runner_state(wiki, "book-next")
    # Sidecar artifacts in gates/ (e.g. Phase 1.5 stats) are not gates and must not drift.
    (gate.parent / "phase-1.5-stats.json").write_text('{"fidelity": 1.0}', encoding="utf-8")
    proc = run_pipeline_next(wiki, "book-next")
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert proc.stdout.count("NEXT:") == 1
    assert "domain-library run library_phase23_blocks" in proc.stdout


def test_pipeline_next_detects_missing_gate(tmp: Path) -> None:
    wiki = tmp / "wiki"
    gate = write_runner_state(wiki, "book-missing-gate")
    gate.unlink()
    proc = run_pipeline_next(wiki, "book-missing-gate")
    assert proc.returncode == 2
    assert "missing gate" in proc.stdout


def test_pipeline_next_detects_gate_phase_mismatch(tmp: Path) -> None:
    wiki = tmp / "wiki"
    write_runner_state(wiki, "book-wrong-gate", declared_phase="9")
    proc = run_pipeline_next(wiki, "book-wrong-gate")
    assert proc.returncode == 2
    assert "declares phase" in proc.stdout


def test_pipeline_next_rejects_unknown_state(tmp: Path) -> None:
    wiki = tmp / "wiki"
    write_runner_state(wiki, "book-unknown", status="MAGIC")
    proc = run_pipeline_next(wiki, "book-unknown")
    assert proc.returncode == 2
    assert "unknown status" in proc.stdout


def test_slug_traversal_rejected_before_filesystem_write(tmp: Path) -> None:
    from domain_library.pipeline import common as pipeline_common
    outside = tmp / "escape"
    try:
        pipeline_common.extraction_root(tmp / "wiki", "../../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("traversal slug accepted")
    assert not outside.exists()


def test_source_hash_collision_rejected(tmp: Path) -> None:
    from _meta.scripts import library_phase1_ocr as phase1
    raw = tmp / "raw"
    raw.mkdir()
    (raw / "source-manifest.json").write_text(json.dumps({"sha256": "a" * 64}), encoding="utf-8")
    try:
        phase1.enforce_source_identity(raw, "same-slug", "b" * 64)
    except RuntimeError as exc:
        assert "different PDF" in str(exc)
    else:
        raise AssertionError("source hash collision accepted")


def test_phase1_chunk_and_resume_behavior(tmp: Path) -> None:
    from _meta.scripts import library_phase1_ocr as phase1
    from pypdf import PdfReader, PdfWriter
    source = tmp / "source.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=72, height=72)
    with source.open("wb") as fh:
        writer.write(fh)
    phase1.PdfWriter = PdfWriter
    chunks_dir = tmp / "chunks"
    first = phase1.make_chunks(PdfReader(source), chunks_dir, max_pages=2, max_bytes=1024 * 1024)
    hashes = [phase1.file_identity(row[3])[0] for row in first]
    second = phase1.make_chunks(PdfReader(source), chunks_dir, max_pages=2, max_bytes=1024 * 1024)
    assert [(row[1], row[2]) for row in second] == [(1, 2), (3, 3)]
    assert [phase1.file_identity(row[3])[0] for row in second] == hashes
    result = tmp / "chunk.json"
    result.write_text(json.dumps({"ok": True, "text": "x" * 120}), encoding="utf-8")
    assert phase1.valid_ocr_result(result)
    result.write_text(json.dumps({"ok": False, "text": "x" * 120}), encoding="utf-8")
    assert not phase1.valid_ocr_result(result)


def test_atomic_json_write_leaves_no_partial_file(tmp: Path) -> None:
    from domain_library.pipeline import common as pipeline_common
    target = tmp / "state.json"
    pipeline_common.write_json(target, {"status": "PASS"})
    assert json.loads(target.read_text(encoding="utf-8"))["status"] == "PASS"
    assert list(tmp.glob(".state.json.*")) == []


def test_ocr_download_retries_and_bounds_bytes(tmp: Path) -> None:
    from _meta.scripts import library_phase1_ocr as phase1

    class Response:
        def __init__(self, status: int, chunks: list[bytes]):
            self.status_code = status
            self.url = "https://assets.ufileos.com/crop.png"
            self.headers = {"Content-Type": "image/png"}
            self.chunks = chunks
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_content(self, chunk_size: int): return iter(self.chunks)

    class Requests:
        def __init__(self, responses): self.responses = iter(responses); self.calls = 0
        def get(self, *args, **kwargs): self.calls += 1; return next(self.responses)

    original_requests, original_sleep = phase1.requests, phase1.time.sleep
    try:
        fake = Requests([Response(429, []), Response(200, [b"ok"])])
        phase1.requests, phase1.time.sleep = fake, lambda _: None
        _, records, failures = phase1.download_assets({"https://assets.ufileos.com/crop.png"}, tmp / "images", 1, max_bytes=10)
        assert fake.calls == 2 and records and not failures
        fake = Requests([Response(200, [b"too-large"])])
        phase1.requests = fake
        _, _, failures = phase1.download_assets({"https://assets.ufileos.com/large.png"}, tmp / "large", 1, max_bytes=2, retries=1)
        assert failures and not any((tmp / "large").glob("*.png"))
    finally:
        phase1.requests, phase1.time.sleep = original_requests, original_sleep


def test_alternate_three_lane_domain_configuration(tmp: Path) -> None:
    from _meta.scripts import library_phase33_dispatch as phase33
    wiki = tmp / "wiki"
    config = json.loads((default_wiki() / "_meta" / "config" / "domain.json").read_text(encoding="utf-8"))
    config["lanes"] = config["lanes"][:3]
    path = wiki / "_meta" / "config" / "domain.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config), encoding="utf-8")
    phase33._load_lanes(wiki)
    assert set(phase33.LANES) == {"defs", "math", "examples"}
    assert len(phase33.validate_agent_profiles()) == 3
    phase33._load_lanes(default_wiki())


def test_finalization_requires_audit_and_reaches_done(tmp: Path) -> None:
    from _meta.scripts import library_audit
    wiki = tmp / "wiki"
    slug = "book-final"
    root = wiki / "_meta" / "extractions" / slug
    root.mkdir(parents=True)
    report = wiki / "_meta" / "reports" / "audit.json"
    (root / "pipeline-state.json").write_text(json.dumps({"slug": slug, "status": "READY_FOR_POST", "current_phase": "5", "completed_phases": ["5"], "gates": {}}), encoding="utf-8")
    assert library_audit.finalize_state(wiki, slug, False, True, report) is False
    assert json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))["status"] == "READY_FOR_POST"
    assert library_audit.finalize_state(wiki, slug, True, True, report) is True
    assert json.loads((root / "pipeline-state.json").read_text(encoding="utf-8"))["status"] == "DONE"
    assert json.loads((root / "gates" / "phase-post.json").read_text(encoding="utf-8"))["status"] == "PASS"




def main() -> None:
    tests = [obj for name, obj in globals().items() if name.startswith("test_")]
    failures: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for test in tests:
            case = tmp / test.__name__; case.mkdir()
            try:
                test(case)
            except Exception:
                import traceback
                failures.append((test.__name__, traceback.format_exc()))
                print(f"FAIL {test.__name__}")
            else:
                print(f"PASS {test.__name__}")
    if failures:
        print(f"\n{len(failures)}/{len(tests)} smoke tests FAILED:")
        for name, tb in failures:
            print(f"\n--- {name} ---\n{tb}")
        raise SystemExit(1)
    print(f"PASS all {len(tests)} smoke tests")


if __name__ == "__main__":
    main()
