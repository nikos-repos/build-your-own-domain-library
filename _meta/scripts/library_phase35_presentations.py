#!/usr/bin/env python3
"""Domain Library Phase 3.5 team-presentation assembly gate.

Phase 3.5 runs after Phase 3.4 specialist output/schema verification. It
assembles one team presentation per current extraction unit, then validates the
presentation artifact itself. Page creation remains Phase 5.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import library_phase31_source_index as phase31
import team_presentation_assembler as assembler
import wiki_integrity
from extraction_units import ExtractionUnit, discover_units

DEFAULT_WIKI = SCRIPT_DIR.parents[1]
RUNNER = "library_phase35_presentations.py"
CITED_BLOCK_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)")
EMBED_RE = re.compile(r"!\[\[[^\]]+#\^([a-z0-9-]+-ch\d+-\d+)[^\]]*\]\]")
REQUIRED_SECTIONS = [header for header, _lanes in assembler.ASSEMBLY_ORDER]
MIN_PRESENTATION_EMBEDS = 2
MIN_AUTHOR_QUOTE_LINES = 2
L009_CATEGORY_SECTIONS = {
    "executive_summary": ["Executive Summary"],
    "author_words": ["Author's Words"],
    "definition": ["Rich Definitions"],
    "formulas": ["Author's Formulation"],
    "examples": ["Specific Example", "Figures and Diagrams", "Implementation Details"],
    "limitations": ["Author's Warnings", "Limitations and Counter-Arguments"],
    "empirical_context": ["Historical / Empirical Context", "Calibration Data Sources"],
    "relations": ["Relations"],
    "evidence_index": ["Unit evidence corpus"],
}
L009_REQUIRED_CATEGORIES = {"author_words", "definition", "formulas", "examples", "limitations", "relations", "evidence_index"}
L009_MIN_CATEGORY_CITATIONS = 2
L009_MIN_CATEGORY_EMBEDS = 2
L009_MONOPOLY_BODY_SHARE = 0.40
L009_EVIDENCE_INDEX_TOTAL_SHARE_NOTICE = 0.60


from pipeline_common import (  # shared plumbing — audit T10
    SLOP_RE,
    extraction_root,
    gate_path,
    load_state,
    manifest_path,
    read_json,
    rel,
    resolve_path,
    state_path,
    utc_now,
    verification_path,
    write_gate,
    write_json,
)
import pipeline_common


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "presentation-report.json"


def evidence_balance_json_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "presentation-evidence-balance-audit.json"


def evidence_balance_md_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "presentation-evidence-balance-audit.md"


def preflight_phase34(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "3.4")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.4 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.4 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "3.4" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 3.4 complete")
    if state.get("status") not in {"READY_FOR_3.5", "IN_PROGRESS", "FAILED"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 3.5: {state.get('status')}")
    if state.get("status") == "FAILED" and state.get("current_phase") != "3.5":
        raise RuntimeError(f"pipeline-state FAILED outside Phase 3.5 retry context: {state.get('current_phase')}")

    verification_ref = gate_data.get("verification_report") or rel(verification_path(wiki, slug), wiki)
    verification_file = resolve_path(verification_ref, wiki)
    if not verification_file.exists():
        raise FileNotFoundError(f"Phase 3.4 verification report not found: {verification_file}")
    verification = read_json(verification_file)
    if verification.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.4 verification report is not PASS: {verification_file}")
    if int(verification.get("checked", 0)) <= 0:
        raise RuntimeError("Phase 3.4 verification report checked no outputs")
    return state, gate_data, verification


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


def count_author_quote_lines(author_words: str) -> int:
    return sum(1 for line in author_words.splitlines() if line.strip().startswith(">") and "![[" not in line and len(line.strip()) >= 20)


def validate_presentation(path: Path, wiki: Path, slug: str, unit: ExtractionUnit, valid_blocks: set[str], vault_index: wiki_integrity.VaultIndex) -> dict[str, Any]:
    issues: list[str] = []
    if not path.exists():
        return {"unit_id": unit.unit_id, "presentation": rel(path, wiki), "exists": False, "issues": ["missing presentation output"]}
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        issues.append("empty presentation output")
    if not text.startswith("---\n"):
        issues.append("missing YAML frontmatter")
    if f'unit_id: "{unit.unit_id}"' not in text:
        issues.append("frontmatter unit_id mismatch or missing")
    if f'source: "[[{slug}]]"' not in text:
        issues.append("frontmatter source mismatch or missing")

    headers = re.findall(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
    duplicates = sorted(header for header, count in Counter(headers).items() if count > 1)
    if duplicates:
        issues.append(f"duplicate section headers: {duplicates}")
    missing_sections = [section for section in REQUIRED_SECTIONS if section not in headers]
    if missing_sections:
        issues.append(f"missing required presentation sections: {missing_sections}")
    extra_sections = sorted(set(headers) - set(REQUIRED_SECTIONS))
    if extra_sections:
        issues.append(f"unexpected presentation sections: {extra_sections}")

    sections = assembler.extract_sections(text)
    empty_sections = [section for section in REQUIRED_SECTIONS if not sections.get(section, "").strip()]
    if empty_sections:
        issues.append(f"empty required presentation sections: {empty_sections}")
    section_missing_blocks = [section for section in REQUIRED_SECTIONS if section in sections and not CITED_BLOCK_RE.findall(sections[section])]
    if section_missing_blocks:
        issues.append(f"sections missing block citations: {section_missing_blocks}")

    block_ids = CITED_BLOCK_RE.findall(text)
    if not block_ids:
        issues.append("no block IDs cited in presentation")
    wrong_slug = sorted({bid for bid in block_ids if not bid.startswith(f"{slug}-")})
    if wrong_slug:
        issues.append(f"wrong-slug block IDs in presentation: {wrong_slug[:10]}")
    unknown = sorted({bid for bid in block_ids if bid.startswith(f"{slug}-") and bid not in valid_blocks})
    if unknown:
        issues.append(f"presentation cites block IDs outside unit source index: {unknown[:10]}")

    embeds = EMBED_RE.findall(text)
    if len(embeds) < MIN_PRESENTATION_EMBEDS:
        issues.append(f"presentation has {len(embeds)} block embeds; minimum is {MIN_PRESENTATION_EMBEDS}")
    unknown_embeds = sorted({bid for bid in embeds if bid not in valid_blocks})
    if unknown_embeds:
        issues.append(f"presentation embeds block IDs outside unit source index: {unknown_embeds[:10]}")

    author_quote_lines = count_author_quote_lines(sections.get("Author's Words", ""))
    if author_quote_lines < MIN_AUTHOR_QUOTE_LINES:
        issues.append(f"Author's Words has {author_quote_lines} substantial quote lines; minimum is {MIN_AUTHOR_QUOTE_LINES}")

    slop = SLOP_RE.search(text)
    if slop:
        issues.append(f"slop/placeholder marker found: {slop.group(0)}")

    dead_links = [f for f in wiki_integrity.check_text(vault_index, text) if f["status"] != "ok"]
    if dead_links:
        sample = "; ".join(f"{f['raw']} [{f['status']}]" for f in dead_links[:5])
        issues.append(f"presentation has {len(dead_links)} unresolvable/non-canonical block links: {sample}")

    return {
        "unit_id": unit.unit_id,
        "presentation": rel(path, wiki),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "line_count": len(text.splitlines()),
        "section_count": len(headers),
        "block_id_count": len(block_ids),
        "unique_block_ids": len(set(block_ids)),
        "block_embed_count": len(embeds),
        "author_quote_lines": author_quote_lines,
        "issues": issues,
    }


def split_relations_and_evidence_index(sections: dict[str, str]) -> dict[str, str]:
    out = dict(sections)
    relations = out.get("Relations", "")
    marker = "Unit evidence corpus:"
    if marker in relations:
        before, after = relations.split(marker, 1)
        out["Relations"] = before
        out["Unit evidence corpus"] = after
    else:
        out["Unit evidence corpus"] = ""
    return out


def category_text(sections: dict[str, str], category: str) -> str:
    return "\n".join(sections.get(section, "") for section in L009_CATEGORY_SECTIONS[category])


def category_metrics(text: str, total_citations: int, body_citations: int, *, body_category: bool) -> dict[str, Any]:
    block_ids = CITED_BLOCK_RE.findall(text)
    embeds = EMBED_RE.findall(text)
    citation_count = len(block_ids)
    return {
        "citation_count": citation_count,
        "unique_block_ids": len(set(block_ids)),
        "block_embed_count": len(embeds),
        "nonempty_lines": sum(1 for line in text.splitlines() if line.strip()),
        "citation_share_total": round(citation_count / total_citations, 4) if total_citations else 0.0,
        "citation_share_body": round(citation_count / body_citations, 4) if body_category and body_citations else 0.0,
    }


def audit_presentation_evidence_balance(path: Path, wiki: Path, row: dict[str, Any]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    sections = split_relations_and_evidence_index(assembler.extract_sections(text))
    category_texts = {category: category_text(sections, category) for category in L009_CATEGORY_SECTIONS}
    body_categories = [category for category in L009_CATEGORY_SECTIONS if category != "evidence_index"]
    total_citations = sum(len(CITED_BLOCK_RE.findall(value)) for value in category_texts.values())
    body_citations = sum(len(CITED_BLOCK_RE.findall(category_texts[category])) for category in body_categories)
    categories = {
        category: category_metrics(
            value,
            total_citations,
            body_citations,
            body_category=category in body_categories,
        )
        for category, value in category_texts.items()
    }
    findings: list[dict[str, Any]] = []
    for category in sorted(L009_REQUIRED_CATEGORIES):
        metrics = categories[category]
        if category != "evidence_index" and metrics["citation_count"] < L009_MIN_CATEGORY_CITATIONS:
            findings.append(
                {
                    "severity": "warning",
                    "code": "thin_citations",
                    "category": category,
                    "message": f"{category} has {metrics['citation_count']} block citations; add source-grounded evidence before Phase 5 page drafting.",
                }
            )
        if category != "evidence_index" and metrics["block_embed_count"] < L009_MIN_CATEGORY_EMBEDS:
            findings.append(
                {
                    "severity": "warning",
                    "code": "thin_embeds",
                    "category": category,
                    "message": f"{category} has {metrics['block_embed_count']} block embeds; add at least {L009_MIN_CATEGORY_EMBEDS} direct embeds or justify the thin section.",
                }
            )
    body_rank = sorted(((category, categories[category]) for category in body_categories), key=lambda item: (-item[1]["citation_count"], item[0]))
    if body_rank:
        top_category, top_metrics = body_rank[0]
        thin_required = [
            category
            for category in sorted(L009_REQUIRED_CATEGORIES - {"evidence_index"})
            if categories[category]["citation_count"] < L009_MIN_CATEGORY_CITATIONS
        ]
        if top_metrics["citation_share_body"] >= L009_MONOPOLY_BODY_SHARE and thin_required:
            findings.append(
                {
                    "severity": "warning",
                    "code": "citation_monopoly_with_thin_sections",
                    "category": top_category,
                    "message": f"{top_category} carries {top_metrics['citation_share_body']:.0%} of body citations while {thin_required} remain citation-thin.",
                }
            )
    evidence_share = categories["evidence_index"]["citation_share_total"]
    if evidence_share >= L009_EVIDENCE_INDEX_TOTAL_SHARE_NOTICE:
        findings.append(
            {
                "severity": "notice",
                "code": "evidence_index_dominates_total_citations",
                "category": "evidence_index",
                "message": f"Evidence index carries {evidence_share:.0%} of all citations; this is acceptable only if body sections remain independently grounded.",
            }
        )
    warning_count = sum(1 for finding in findings if finding["severity"] == "warning")
    return {
        "unit_id": row["unit_id"],
        "presentation": row["presentation"],
        "status": "WARN" if warning_count else "PASS",
        "body_citation_count": body_citations,
        "total_citation_count": total_citations,
        "categories": categories,
        "dominant_body_category": body_rank[0][0] if body_rank else None,
        "dominant_body_share": body_rank[0][1]["citation_share_body"] if body_rank else 0.0,
        "finding_count": len(findings),
        "warning_count": warning_count,
        "findings": findings,
    }


def build_evidence_balance_audit(wiki: Path, slug: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    unit_audits = []
    for row in rows:
        path = resolve_path(row["presentation"], wiki)
        unit_audits.append(audit_presentation_evidence_balance(path, wiki, row))
    warning_count = sum(int(item["warning_count"]) for item in unit_audits)
    return {
        "schema_version": 1,
        "lesson_candidate": "L-009",
        "status": "WARN" if warning_count else "PASS",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "scope": "post_phase_3_5_presentation_evidence_balance_audit",
        "required_categories": sorted(L009_REQUIRED_CATEGORIES),
        "unit_count": len(unit_audits),
        "warning_count": warning_count,
        "finding_count": sum(int(item["finding_count"]) for item in unit_audits),
        "units": unit_audits,
    }


def render_evidence_balance_markdown(audit: dict[str, Any]) -> str:
    lines = [
        f"# Presentation Evidence-Balance Audit — {audit['slug']}",
        "",
        "lesson_candidate: L-009",
        f"status: {audit['status']}",
        f"unit_count: {audit['unit_count']}",
        f"warning_count: {audit['warning_count']}",
        "",
        "Post-assembly audit only. This report does not lower Phase 3.5 gates, force unsupported sections, or write concept pages.",
        "",
    ]
    for unit in audit["units"]:
        lines.extend(
            [
                f"## Unit `{unit['unit_id']}`",
                "",
                f"- status: {unit['status']}",
                f"- body_citation_count: {unit['body_citation_count']}",
                f"- total_citation_count: {unit['total_citation_count']}",
                f"- dominant_body_category: {unit['dominant_body_category']} ({unit['dominant_body_share']:.0%})",
                "",
                "| Category | Citations | Unique blocks | Embeds | Body share | Total share |",
                "|---|---:|---:|---:|---:|---:|",
            ]
        )
        for category, metrics in unit["categories"].items():
            lines.append(
                f"| {category} | {metrics['citation_count']} | {metrics['unique_block_ids']} | {metrics['block_embed_count']} | {metrics['citation_share_body']:.0%} | {metrics['citation_share_total']:.0%} |"
            )
        lines.extend(["", "### Findings", ""])
        if unit["findings"]:
            for finding in unit["findings"]:
                lines.append(f"- **{finding['severity']} / {finding['code']} / {finding['category']}** — {finding['message']}")
        else:
            lines.append("- none")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def update_manifest(wiki: Path, slug: str, report: dict[str, Any]) -> None:
    path = manifest_path(wiki, slug)
    if not path.exists():
        return
    manifest = read_json(path)
    manifest["presentation_summary"] = {
        "status": report["status"],
        "generated_at": report["generated_at"],
        "runner": RUNNER,
        "unit_count": report["unit_count"],
        "failed": report["failed"],
        "report": rel(report_path(wiki, slug), wiki),
    }
    manifest["presentations"] = [
        {
            "unit_id": item["unit_id"],
            "output": item["presentation"],
            "status": "PASS" if not item["issues"] else "FAIL",
            "block_embed_count": item.get("block_embed_count", 0),
            "author_quote_lines": item.get("author_quote_lines", 0),
        }
        for item in report["presentations"]
    ]
    manifest.setdefault("source_reports", {})["presentation_report"] = rel(report_path(wiki, slug), wiki)
    if "evidence_balance_audit" in report:
        manifest.setdefault("source_reports", {})["presentation_evidence_balance_audit"] = report["evidence_balance_audit"]
    write_json(path, manifest)


def run_presentations(wiki: Path, slug: str) -> tuple[dict[str, Any], list[str]]:
    _state, phase34_gate, verification = preflight_phase34(wiki, slug)
    chapters_dir = wiki / "raw" / "papers" / slug / "chapters"
    if not chapters_dir.exists():
        raise FileNotFoundError(f"chapters directory not found: {chapters_dir}")
    units = discover_current_units(chapters_dir, slug)
    expected_checked = len(units) * len(assembler.LANE_FILES)
    if int(verification.get("checked", 0)) != expected_checked:
        raise RuntimeError(f"Phase 3.4 checked {verification.get('checked')} outputs; expected {expected_checked}")

    failures: list[str] = []
    rows: list[dict[str, Any]] = []
    vault_index = wiki_integrity.build_vault_index(wiki)
    for unit in units:
        team_dir = extraction_root(wiki, slug) / f"team-{unit.unit_id}"
        if not team_dir.exists():
            raise FileNotFoundError(f"team directory not found: {team_dir}")
        chapter_ref = wiki_integrity.vault_ref(Path(unit.chapter_path), wiki)
        output = assembler.assemble(team_dir, slug, unit.unit_id, chapter_ref)
        row = validate_presentation(output, wiki, slug, unit, source_blocks_for_unit(wiki, slug, unit), vault_index)
        rows.append(row)
        failures.extend(f"{unit.unit_id}: {issue}" for issue in row["issues"])

    evidence_balance = build_evidence_balance_audit(wiki, slug, rows)
    write_json(evidence_balance_json_path(wiki, slug), evidence_balance)
    evidence_balance_md_path(wiki, slug).write_text(render_evidence_balance_markdown(evidence_balance), encoding="utf-8")

    report = {
        "schema_version": 1,
        "status": "FAIL" if failures else "PASS",
        "slug": slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "phase_3_4_gate": phase34_gate,
        "unit_count": len(units),
        "checked": len(rows),
        "failed": sum(1 for row in rows if row["issues"]),
        "required_sections": REQUIRED_SECTIONS,
        "min_block_embeds": MIN_PRESENTATION_EMBEDS,
        "min_author_quote_lines": MIN_AUTHOR_QUOTE_LINES,
        "presentations": rows,
        "failures": failures,
        "evidence_balance_audit": rel(evidence_balance_json_path(wiki, slug), wiki),
        "evidence_balance_markdown": rel(evidence_balance_md_path(wiki, slug), wiki),
        "evidence_balance_status": evidence_balance["status"],
        "evidence_balance_warning_count": evidence_balance["warning_count"],
    }
    return report, failures


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run Domain Library Phase 3.5 team presentation assembly gate")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--wiki", default=str(DEFAULT_WIKI))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    wiki = Path(args.wiki).resolve()
    slug = pipeline_common.validate_slug(args.slug)
    gates: dict[str, str] = {}
    completed: list[str] = []
    try:
        state = load_state(wiki, slug)
        gates.update({str(k): str(v) for k, v in state.get("gates", {}).items()})
        completed = [str(x) for x in state.get("completed_phases", [])]
        report, failures = run_presentations(wiki, slug)
        write_json(report_path(wiki, slug), report)
        update_manifest(wiki, slug, report)
        if failures:
            raise RuntimeError(f"Phase 3.5 presentation validation failed with {len(failures)} issue(s)")
        phase35_gate = write_gate(
            wiki,
            slug,
            "3.5",
            "PASS",
            {
                "presentation_report": rel(report_path(wiki, slug), wiki),
                "unit_count": report["unit_count"],
                "checked": report["checked"],
                "failed": report["failed"],
                "evidence_balance_audit": rel(evidence_balance_json_path(wiki, slug), wiki),
            },
        )
        gates["3.5"] = rel(phase35_gate, wiki)
        if "3.5" not in completed:
            completed.append("3.5")
        write_state(wiki, slug, "READY_FOR_4", "3.5", completed, gates)
    except Exception as exc:
        fail_gate = write_gate(wiki, slug, "3.5", "FAIL", {"reason": str(exc), "presentation_report": rel(report_path(wiki, slug), wiki)})
        gates["3.5"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "3.5", completed, gates)
        if not report_path(wiki, slug).exists():
            write_json(
                report_path(wiki, slug),
                {
                    "schema_version": 1,
                    "status": "FAIL",
                    "slug": slug,
                    "generated_at": utc_now(),
                    "generated_by": RUNNER,
                    "checked": 0,
                    "failed": 0,
                    "presentations": [],
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
                "phase_3_5_gate": gates["3.5"],
                "presentation_report": rel(report_path(wiki, slug), wiki),
                "checked": report["checked"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
