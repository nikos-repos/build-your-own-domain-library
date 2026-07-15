#!/usr/bin/env python3
"""Domain Library Phase 5 canonical page writer.

Pages are created only after Phase 4 user-confirmation PASS and only from the
validated team-presentation layer. Phase 4 concepts choose what to write; team
presentations provide the source-grounded prose and evidence blocks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from domain_library.paths import default_wiki
from domain_library.pipeline.cli import pipeline_parser
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

from _meta.scripts import blockid_validator
import latex_slug_filter
from _meta.scripts import team_presentation_assembler as presentation_assembler
from _meta.scripts import wiki_integrity
from _meta.scripts import yaml_serializer

try:
    import yaml
except ImportError:  # pragma: no cover - yaml_serializer already enforces this at import time.
    yaml = None

DEFAULT_WIKI = default_wiki()
RUNNER = "library_phase5_pages.py"
CITED_BLOCK_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)")
EMBED_RE = re.compile(r"!\[\[[^\]]+#\^([a-z0-9-]+-ch\d+-\d+)[^\]]*\]\]")
SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,120}$")
REQUIRED_SECTIONS = [
    "Author's Words",
    "Source-grounded definition",
    "Specific Example",
    "Relations",
    "Evidence index",
]
PAGE_SECTIONS = [
    ("Author's Words", "Author's Words"),
    ("Source-grounded definition", "Rich Definitions"),
    ("Author's Formulation", "Author's Formulation"),
    ("Specific Example", "Specific Example"),
    ("Implementation Details", "Implementation Details"),
    ("Figures and Diagrams", "Figures and Diagrams"),
    ("Author's Warnings", "Author's Warnings"),
    ("Limitations and Counter-Arguments", "Limitations and Counter-Arguments"),
    ("Historical / Empirical Context", "Historical / Empirical Context"),
]
MIN_CONCEPT_LINES = 80
MIN_BLOCK_EMBEDS = 2
MIN_AUTHOR_QUOTES = 2


@dataclass
class Presentation:
    unit_id: str
    path: Path
    text: str
    sections: dict[str, str]
    block_ids: set[str]
    embeds: list[str]


from domain_library.pipeline.common import (  # shared plumbing — audit T10
    SLOP_RE,
    confirmation_path,
    confirmed_path,
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


def domain_slug() -> str:
    return pipeline_common.load_domain_config(DEFAULT_WIKI)["tenant"]


def write_state(wiki: Path, slug: str, status: str, current_phase: str, completed: list[str], gates: dict[str, str]) -> None:
    pipeline_common.write_state(wiki, slug, status, current_phase, completed, gates, runner=RUNNER)



def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def concepts_dir(wiki: Path) -> Path:
    return wiki / "concepts"


def page_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "page-build-report.json"


def presentation_report_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "presentation-report.json"


def preflight_phase4(wiki: Path, slug: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state = load_state(wiki, slug)
    gate = gate_path(wiki, slug, "4")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 4 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 4 gate is not PASS: {gate}")
    completed = set(str(x) for x in state.get("completed_phases", []))
    if "4" not in completed:
        raise RuntimeError("pipeline-state.json does not mark Phase 4 complete")
    if state.get("status") not in {"READY_FOR_5", "IN_PROGRESS", "FAILED"}:
        raise RuntimeError(f"pipeline-state status is not ready for Phase 5: {state.get('status')}")
    if state.get("status") == "FAILED" and state.get("current_phase") != "5":
        raise RuntimeError(f"pipeline-state FAILED outside Phase 5 retry context: {state.get('current_phase')}")
    confirmation_ref = gate_data.get("confirmation") or rel(confirmation_path(wiki, slug), wiki)
    confirmation_file = resolve_path(confirmation_ref, wiki)
    if not confirmation_file.exists():
        raise FileNotFoundError(f"Phase 4 confirmation not found: {confirmation_file}")
    confirmation = read_json(confirmation_file)
    if confirmation.get("status") != "PASS" or int(confirmation.get("selected_count", 0)) <= 0:
        raise RuntimeError(f"Phase 4 confirmation is not a non-empty PASS: {confirmation_file}")
    master_ref = gate_data.get("master_confirmed") or rel(confirmed_path(wiki, slug), wiki)
    master_file = resolve_path(master_ref, wiki)
    if not master_file.exists():
        raise FileNotFoundError(f"master-confirmed.json not found: {master_file}")
    confirmed = read_json(master_file)
    if confirmed.get("status") != "PASS" or int(confirmed.get("selected_concepts", 0)) <= 0:
        raise RuntimeError(f"master-confirmed.json is not a non-empty PASS: {master_file}")
    return state, gate_data, confirmed


def require_phase35_presentations(wiki: Path, slug: str) -> dict[str, Any]:
    gate = gate_path(wiki, slug, "3.5")
    if not gate.exists():
        raise FileNotFoundError(f"Phase 3.5 gate not found: {gate}")
    gate_data = read_json(gate)
    if gate_data.get("status") != "PASS":
        raise RuntimeError(f"Phase 3.5 gate is not PASS: {gate}")
    report = resolve_path(gate_data.get("presentation_report") or rel(presentation_report_path(wiki, slug), wiki), wiki)
    if not report.exists():
        raise FileNotFoundError(f"presentation-report.json not found: {report}")
    data = read_json(report)
    if data.get("status") != "PASS" or int(data.get("checked", 0)) <= 0:
        raise RuntimeError(f"presentation-report.json is not a non-empty PASS: {report}")
    return data


def load_presentations(wiki: Path, slug: str, report: dict[str, Any]) -> dict[str, Presentation]:
    presentations: dict[str, Presentation] = {}
    for item in report.get("presentations", []):
        if not isinstance(item, dict):
            continue
        unit_id = str(item.get("unit_id", ""))
        path_value = item.get("presentation")
        if not unit_id or not path_value:
            raise RuntimeError(f"invalid presentation report row: {item}")
        path = resolve_path(path_value, wiki)
        if not path.exists() or path.stat().st_size == 0:
            raise FileNotFoundError(f"missing presentation file for {unit_id}: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = presentation_assembler.extract_sections(text)
        presentations[unit_id] = Presentation(
            unit_id=unit_id,
            path=path,
            text=text,
            sections=sections,
            block_ids=set(CITED_BLOCK_RE.findall(text)),
            embeds=EMBED_RE.findall(text),
        )
    if not presentations:
        raise RuntimeError("no presentations loaded from presentation-report.json")
    return presentations


def block_to_presentations(presentations: dict[str, Presentation]) -> dict[str, list[Presentation]]:
    out: dict[str, list[Presentation]] = {}
    for presentation in presentations.values():
        for block_id in presentation.block_ids:
            out.setdefault(block_id, []).append(presentation)
    return out


def collect_block_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        direct = value.get("block_id")
        if isinstance(direct, str) and direct:
            found.append(direct)
        many = value.get("block_ids")
        if isinstance(many, list):
            found.extend(str(item) for item in many if isinstance(item, str) and item)
        for item in value.values():
            found.extend(collect_block_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(collect_block_ids(item))
    return found


def concept_blocks(concept: dict[str, Any]) -> list[str]:
    out = []
    for block_id in collect_block_ids(concept):
        if block_id not in out:
            out.append(block_id)
    return out


def clean_title(value: str) -> str:
    return re.sub(r"^\s*\d+(?:\.\d+)*\s+", "", value.strip())


BLOCK_ANCHOR_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)(?=\s|$)", re.MULTILINE)


def chapter_ref_map(wiki: Path, source_slug: str) -> dict[str, str]:
    """block_id -> vault-absolute wikilink target of the owning chapter file.

    Embeds must point at the actual chapter note so they resolve in Obsidian;
    `.orig.` pre-split copies are skipped so every anchor has one owner.
    """
    chapters = wiki / "raw" / "papers" / source_slug / "chapters"
    refs: dict[str, str] = {}
    for md in sorted(chapters.glob("*.md")):
        if ".orig." in md.name:
            continue
        ref = wiki_integrity.vault_ref(md, wiki)
        for block_id in BLOCK_ANCHOR_RE.findall(md.read_text(encoding="utf-8", errors="replace")):
            refs.setdefault(block_id, ref)
    return refs


def section_text(presentations: list[Presentation], section: str) -> str:
    chunks: list[str] = []
    for presentation in presentations:
        text = presentation.sections.get(section, "").strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def quote_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip().startswith(">") and "![[" not in line and len(line.strip()) >= 20]


def short_anchor(block_id: str, source_slug: str) -> str:
    """Human-readable alias for Relations links: 'ch10-0400' instead of the full ID."""
    return block_id[len(source_slug) + 1 :] if block_id.startswith(f"{source_slug}-") else block_id


def normalize_section_body(text: str, fallback: str, evidence_blocks: list[str], source_slug: str, refs: dict[str, str]) -> str:
    cleaned = text.strip()
    if cleaned:
        return cleaned
    if evidence_blocks:
        block_id = evidence_blocks[0]
        return f"{fallback} See source block ^{block_id}.\n\n> ![[{refs.get(block_id, source_slug)}#^{block_id}]]"
    return fallback


def render_relations(source_slug: str, evidence_blocks: list[str], concept: dict[str, Any], refs: dict[str, str]) -> str:
    lines = ["## Relations", ""]
    primary_name = concept.get("name") or concept.get("slug")

    def edge(predicate: str, block_id: str) -> str:
        target = refs.get(block_id, source_slug)
        return f"- {predicate}::[[{target}#^{block_id}|^{short_anchor(block_id, source_slug)}]]"

    for block_id in evidence_blocks:
        lines.extend(
            [
                edge("extracted_from", block_id),
                f"  - `{primary_name}` is created from the validated team presentation evidence anchored at block `{block_id}`.",
            ]
        )
    if evidence_blocks:
        lines.extend(
            [
                edge("defined_by", evidence_blocks[0]),
                f"  - Primary source-grounded definition evidence for `{primary_name}`.",
            ]
        )
    formula_blocks = collect_block_ids(concept.get("formulas", []))
    for block_id in formula_blocks[:3]:
        lines.extend(
            [
                edge("formulated_by", block_id),
                "  - Formula evidence preserved from schema extraction and team presentation context.",
            ]
        )
    warning_blocks = collect_block_ids(concept.get("warnings", []))
    for block_id in warning_blocks[:3]:
        lines.extend(
            [
                edge("warned_by", block_id),
                "  - Caveat or limitation evidence preserved from source-grounded extraction.",
            ]
        )
    return "\n".join(lines).rstrip()


def render_evidence_index(source_slug: str, evidence_blocks: list[str], presentations: list[Presentation], refs: dict[str, str]) -> str:
    lines = ["## Evidence index", ""]
    by_unit = {presentation.unit_id: presentation for presentation in presentations}
    for idx, block_id in enumerate(evidence_blocks, start=1):
        units = [presentation.unit_id for presentation in presentations if block_id in presentation.block_ids]
        unit_label = ", ".join(units) if units else "unknown unit"
        lines.extend(
            [
                f"{idx}. `^{block_id}` — unit(s): {unit_label}",
                f"   - ![[{refs.get(block_id, source_slug)}#^{block_id}]]",
            ]
        )
    if not evidence_blocks:
        lines.append("- No evidence blocks were available; this page should have failed validation.")
    lines.extend(["", "## Source presentation files", ""])
    for unit_id, presentation in sorted(by_unit.items()):
        lines.append(f"- `{unit_id}` — `{presentation.path.name}`")
    return "\n".join(lines).rstrip()


def render_page(source_slug: str, concept: dict[str, Any], relevant_presentations: list[Presentation], evidence_blocks: list[str], refs: dict[str, str]) -> str:
    """Render the page from presentation content only. There is deliberately
    no depth padding: a page below MIN_CONCEPT_LINES fails validation so the
    thin extraction gets fixed upstream instead of papered over (audit T14)."""
    title = clean_title(str(concept.get("name") or concept.get("slug") or "Untitled concept"))
    confidence = min(0.95, float(concept.get("confidence", 0.5) or 0.5))  # PAGE_SCHEMA cap: never absolute
    first_block = evidence_blocks[0]

    authors_words = section_text(relevant_presentations, "Author's Words")
    rich_def = section_text(relevant_presentations, "Rich Definitions") or section_text(relevant_presentations, "Executive Summary")
    section_bodies = [(header, section_text(relevant_presentations, presentation_header)) for header, presentation_header in PAGE_SECTIONS[2:]]

    real_sections = sum(1 for body in [authors_words, rich_def, *[b for _h, b in section_bodies]] if body.strip())
    total_sections = 2 + len(section_bodies)
    quote_count = len(quote_lines(authors_words))
    quality = round(
        0.5 * (real_sections / total_sections) + 0.3 * min(1.0, quote_count / 4) + 0.2 * min(1.0, len(evidence_blocks) / 8),
        2,
    )
    quality_notes = f"computed at build: {real_sections}/{total_sections} sections with source content, {quote_count} author quote lines, {len(evidence_blocks)} evidence blocks"

    frontmatter = yaml_serializer.build_frontmatter(
        title=title,
        confidence=confidence,
        tier="working",
        author="orchestrator",
        scope="private",
        quality=quality,
        quality_notes=quality_notes,
    )
    parts = [
        frontmatter.rstrip(),
        "",
        "- conforms_to::[[concept-form-contract]]",
        "- has_status::[[growing]]",
        f"- in_domain::[[{domain_slug()}]]",
        "",
        f"# {title}",
        "",
        "> [!abstract] Source-grounded extraction",
        f"> ![[{refs.get(first_block, source_slug)}#^{first_block}]]",
        "",
    ]

    parts.extend(["## Author's Words", "", normalize_section_body(authors_words, "No direct author quote section was available in the team presentation.", evidence_blocks, source_slug, refs), ""])
    parts.extend(["## Source-grounded definition", "", normalize_section_body(rich_def, "Definition evidence is source-grounded in the listed blocks.", evidence_blocks, source_slug, refs), ""])
    for page_header, body in section_bodies:
        parts.extend([f"## {page_header}", "", normalize_section_body(body, f"No separate `{page_header}` content was present for this concept; provenance remains anchored below.", evidence_blocks, source_slug, refs), ""])

    parts.extend([render_relations(source_slug, evidence_blocks, concept, refs), "", render_evidence_index(source_slug, evidence_blocks, relevant_presentations, refs), ""])
    return "\n".join(parts).rstrip() + "\n"


def parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        raise RuntimeError("missing YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise RuntimeError("malformed YAML frontmatter")
    if yaml is None:
        return {}
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise RuntimeError("YAML frontmatter did not parse to object")
    return data


def validate_page(path: Path, wiki: Path, source_slug: str, concept_slug: str, presentation_block_ids: set[str], chapter_block_ids: set[str], vault_index: wiki_integrity.VaultIndex) -> dict[str, Any]:
    issues: list[str] = []
    if not path.exists():
        return {"concept_slug": concept_slug, "path": rel(path, wiki), "exists": False, "issues": ["missing page"]}
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        frontmatter = parse_frontmatter(text)
    except Exception as exc:
        frontmatter = {}
        issues.append(str(exc))
    expected_keys = ["title", "created", "updated", "confidence", "last_reinforced", "tier", "quality", "quality_notes", "scope", "author"]
    found_key_order = []
    if text.startswith("---\n"):
        for line in text.split("---", 2)[1].splitlines():
            if ":" in line:
                found_key_order.append(line.split(":", 1)[0].strip())
    if found_key_order[: len(expected_keys)] != expected_keys:
        issues.append(f"frontmatter key order mismatch: {found_key_order[:len(expected_keys)]}")
    for key in expected_keys:
        if key not in frontmatter:
            issues.append(f"frontmatter missing {key}")
    for required in ["- conforms_to::[[concept-form-contract]]", "- has_status::[[growing]]", f"- in_domain::[[{domain_slug()}]]"]:
        if required not in text:
            issues.append(f"missing classification predicate: {required}")
    if "derived_from::" in text:
        issues.append("uses forbidden derived_from:: predicate")
    if "extracted_from::" not in text:
        issues.append("missing extracted_from:: provenance")
    headers = re.findall(r"^##\s+(.+?)\s*$", text, flags=re.MULTILINE)
    for section in REQUIRED_SECTIONS:
        if section not in headers:
            issues.append(f"missing required section: {section}")
    if len(text.splitlines()) < MIN_CONCEPT_LINES:
        issues.append(f"page has {len(text.splitlines())} lines; minimum is {MIN_CONCEPT_LINES}")
    embeds = EMBED_RE.findall(text)
    if len(embeds) < MIN_BLOCK_EMBEDS:
        issues.append(f"page has {len(embeds)} block embeds; minimum is {MIN_BLOCK_EMBEDS}")
    quote_count = len(quote_lines(presentation_assembler.extract_sections(text).get("Author's Words", "")))
    if quote_count < MIN_AUTHOR_QUOTES:
        issues.append(f"Author's Words has {quote_count} substantial quote lines; minimum is {MIN_AUTHOR_QUOTES}")
    block_ids = set(CITED_BLOCK_RE.findall(text))
    wrong_slug = sorted(block_id for block_id in block_ids if not block_id.startswith(f"{source_slug}-"))
    if wrong_slug:
        issues.append(f"wrong-slug block IDs: {wrong_slug[:10]}")
    outside_presentations = sorted(block_id for block_id in block_ids if block_id.startswith(f"{source_slug}-") and block_id not in presentation_block_ids)
    if outside_presentations:
        issues.append(f"page cites block IDs not present in team presentations: {outside_presentations[:10]}")
    dead = sorted(block_id for block_id in block_ids if block_id.startswith(f"{source_slug}-") and block_id not in chapter_block_ids)
    if dead:
        issues.append(f"page cites dead chapter block IDs: {dead[:10]}")
    slop = SLOP_RE.search(text)
    if slop:
        issues.append(f"slop/placeholder marker found: {slop.group(0)}")
    dead_links = [f for f in wiki_integrity.check_text(vault_index, text) if f["status"] != "ok"]
    if dead_links:
        sample = "; ".join(f"{f['raw']} [{f['status']}]" for f in dead_links[:5])
        issues.append(f"page has {len(dead_links)} unresolvable/non-canonical block links: {sample}")
    return {
        "concept_slug": concept_slug,
        "path": rel(path, wiki),
        "exists": True,
        "size_bytes": path.stat().st_size,
        "line_count": len(text.splitlines()),
        "block_embed_count": len(embeds),
        "quote_count": quote_count,
        "block_id_count": len(block_ids),
        "issues": issues,
    }


def update_index(wiki: Path, page_paths: list[Path]) -> None:
    index = wiki / "index.md"
    if index.exists():
        text = index.read_text(encoding="utf-8", errors="replace")
    else:
        text = "# Domain Library Index\n"
    if "## Extracted Concepts" not in text:
        text = text.rstrip() + "\n\n## Extracted Concepts\n"
    lines = text.rstrip().splitlines()
    existing = set(re.findall(r"\[\[([^\]]+)\]\]", text))
    additions = []
    for path in sorted(page_paths, key=lambda p: p.stem):
        if path.stem not in existing:
            additions.append(f"- [[{path.stem}]]")
    if additions:
        lines.extend(additions)
    index.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def append_log(wiki: Path, source_slug: str, page_paths: list[Path]) -> None:
    pages = ", ".join(f"`{path.stem}`" for path in sorted(page_paths, key=lambda p: p.stem))
    pipeline_common.append_log(wiki, "create", f"{len(page_paths)} concept page(s) for `{source_slug}`: {pages}", RUNNER)


def build_pages(wiki: Path, source_slug: str, force: bool) -> tuple[dict[str, Any], list[str]]:
    _state, phase4_gate, confirmed = preflight_phase4(wiki, source_slug)
    presentation_report = require_phase35_presentations(wiki, source_slug)
    presentations = load_presentations(wiki, source_slug, presentation_report)
    block_map = block_to_presentations(presentations)
    presentation_block_ids = set(block_map)
    chapter_block_ids = blockid_validator.collect_block_ids_from_chapters(wiki / "raw" / "papers" / source_slug / "chapters", source_slug)
    if not chapter_block_ids:
        raise RuntimeError("no chapter block IDs found for Phase 5 validation")
    refs = chapter_ref_map(wiki, source_slug)
    vault_index = wiki_integrity.build_vault_index(wiki)

    concepts = confirmed.get("concepts", {})
    if not isinstance(concepts, dict) or not concepts:
        raise RuntimeError("master-confirmed.json has no concepts object")
    out_dir = concepts_dir(wiki)
    out_dir.mkdir(parents=True, exist_ok=True)
    page_rows: list[dict[str, Any]] = []
    failures: list[str] = []
    written: list[Path] = []

    for concept_slug, concept in concepts.items():
        if not isinstance(concept, dict):
            failures.append(f"{concept_slug}: concept payload is not an object")
            continue
        if not SAFE_SLUG_RE.match(concept_slug) or not latex_slug_filter.is_clean_slug(concept_slug):
            failures.append(f"{concept_slug}: unsafe or filtered concept slug")
            continue
        blocks = concept_blocks(concept)
        if not blocks:
            failures.append(f"{concept_slug}: no block IDs in confirmed concept")
            continue
        evidence_blocks = [block_id for block_id in blocks if block_id in presentation_block_ids]
        if not evidence_blocks:
            failures.append(f"{concept_slug}: no confirmed concept block IDs appear in team presentations")
            continue
        relevant: list[Presentation] = []
        seen_units: set[str] = set()
        for block_id in evidence_blocks:
            for presentation in block_map.get(block_id, []):
                if presentation.unit_id not in seen_units:
                    relevant.append(presentation)
                    seen_units.add(presentation.unit_id)
        if not relevant:
            failures.append(f"{concept_slug}: no relevant team presentations found")
            continue
        page_path = out_dir / f"{concept_slug}.md"
        if page_path.exists() and not force:
            failures.append(f"{concept_slug}: page already exists; rerun with --force only for intentional overwrite")
            continue
        page_text = render_page(source_slug, concept, relevant, evidence_blocks, refs)
        page_path.write_text(page_text, encoding="utf-8")
        validation = validate_page(page_path, wiki, source_slug, concept_slug, presentation_block_ids, chapter_block_ids, vault_index)
        if validation["issues"]:
            failures.extend(f"{concept_slug}: {issue}" for issue in validation["issues"])
        page_rows.append({**validation, "source_presentations": [rel(p.path, wiki) for p in relevant], "evidence_blocks": evidence_blocks})
        written.append(page_path)

    if written:
        update_index(wiki, written)
        append_log(wiki, source_slug, written)

    report = {
        "schema_version": 1,
        "status": "FAIL" if failures else "PASS",
        "slug": source_slug,
        "generated_at": utc_now(),
        "generated_by": RUNNER,
        "phase_4_gate": phase4_gate,
        "confirmed_concepts": len(concepts),
        "pages_written": len(written),
        "concepts_dir": rel(out_dir, wiki),
        "min_lines": MIN_CONCEPT_LINES,
        "min_block_embeds": MIN_BLOCK_EMBEDS,
        "min_author_quotes": MIN_AUTHOR_QUOTES,
        "pages": page_rows,
        "failures": failures,
    }
    return report, failures


def parse_args() -> argparse.Namespace:
    ap = pipeline_parser("Run Domain Library Phase 5 canonical team-presentation page writer", default=DEFAULT_WIKI)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--force", action="store_true", help="Overwrite existing concept pages intentionally")
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
        report, failures = build_pages(wiki, slug, args.force)
        write_json(page_report_path(wiki, slug), report)
        if failures:
            raise RuntimeError(f"Phase 5 page validation failed with {len(failures)} issue(s)")
        phase5_gate = write_gate(
            wiki,
            slug,
            "5",
            "PASS",
            {
                "page_build_report": rel(page_report_path(wiki, slug), wiki),
                "pages_written": report["pages_written"],
                "confirmed_concepts": report["confirmed_concepts"],
            },
        )
        gates["5"] = rel(phase5_gate, wiki)
        if "5" not in completed:
            completed.append("5")
        write_state(wiki, slug, "READY_FOR_POST", "5", completed, gates)
    except Exception as exc:
        fail_gate = write_gate(wiki, slug, "5", "FAIL", {"reason": str(exc), "page_build_report": rel(page_report_path(wiki, slug), wiki)})
        gates["5"] = rel(fail_gate, wiki)
        write_state(wiki, slug, "FAILED", "5", completed, gates)
        if not page_report_path(wiki, slug).exists():
            write_json(
                page_report_path(wiki, slug),
                {
                    "schema_version": 1,
                    "status": "FAIL",
                    "slug": slug,
                    "generated_at": utc_now(),
                    "generated_by": RUNNER,
                    "pages": [],
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
                "phase_5_gate": gates["5"],
                "page_build_report": rel(page_report_path(wiki, slug), wiki),
                "pages_written": report["pages_written"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
