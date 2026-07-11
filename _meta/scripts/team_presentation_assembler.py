#!/usr/bin/env python3
"""Assemble a team presentation from named specialist lane outputs."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_common import configured_lanes

# Lane files and assembly order come from _meta/config/domain.json lane order and required_sections.
_LANES = configured_lanes(Path(__file__).resolve().parents[2])
LANE_FILES = {lane_id: spec["output"] for lane_id, spec in _LANES.items()}
ASSEMBLY_ORDER = [
    (section, [lane_id])
    for lane_id, spec in _LANES.items()
    for section in spec["required_sections"]
]


def extract_sections(text: str) -> dict[str, str]:
    text = text.replace("\r\n", "\n").strip()
    if text.startswith("```markdown"):
        text = text[len("```markdown"):].strip()
    if text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    parts = re.split(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    sections = {}
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections.setdefault(header, body)
    return sections

BLOCK_ID_RE = re.compile(r"\^([a-z0-9-]+-ch\d+-\d+)")
SOURCE_INDEX_ROW_RE = re.compile(r'^- \[([a-z0-9-]+-ch\d+-\d+)\] — "(.*?)"', re.MULTILINE)


def source_evidence(source_index: Path) -> list[tuple[str, str]]:
    if not source_index.exists():
        return []
    text = source_index.read_text(encoding="utf-8", errors="replace")
    rows = SOURCE_INDEX_ROW_RE.findall(text)
    if rows:
        return rows
    return [(bid, bid) for bid in re.findall(r"\b([a-z0-9-]+-ch\d+-\d+)\b", text)]


def with_section_evidence(body: str, evidence: list[tuple[str, str]], embed_target: str) -> str:
    body = body.strip()
    if not evidence:
        return body
    if not BLOCK_ID_RE.search(body):
        anchors = "\n".join(f"- ![[{embed_target}#^{bid}]]" for bid, _text in evidence[:2])
        body = f"{body}\n\nEvidence anchors:\n{anchors}"
    return body


def with_author_quotes(body: str, evidence: list[tuple[str, str]], embed_target: str) -> str:
    # Deliberately no quote synthesis: if the defs lane delivered fewer
    # than the required Author's Words quotes, Phase 3.5 must FAIL so the lane
    # is re-run, instead of the assembler papering over thin extraction.
    return with_section_evidence(body, evidence, embed_target)



def with_unit_evidence_corpus(body: str, evidence: list[tuple[str, str]], embed_target: str) -> str:
    body = with_section_evidence(body, evidence, embed_target)
    if not evidence:
        return body
    cited = set(BLOCK_ID_RE.findall(body))
    missing = [(bid, text) for bid, text in evidence if bid not in cited]
    if not missing:
        return body
    lines = ["", "Unit evidence corpus:"]
    for bid, text in missing:
        clean = text.strip() or bid
        lines.append(f"- ![[{embed_target}#^{bid}]] — {clean}")
    return body.rstrip() + "\n" + "\n".join(lines)





def assemble(team_dir: Path, slug: str, unit_id: str, chapter_ref: str) -> Path:
    """Assemble the team presentation. chapter_ref is the vault-absolute
    wikilink target of the unit's chapter file (no .md) — every evidence
    embed the assembler adds must resolve in Obsidian."""
    if not chapter_ref or chapter_ref in {"source", slug, unit_id}:
        raise ValueError(f"chapter_ref must be the chapter file's vault path, got: {chapter_ref!r}")
    lane_sections = {}
    for lane, fname in LANE_FILES.items():
        path = team_dir / fname
        lane_sections[lane] = extract_sections(path.read_text(encoding="utf-8")) if path.exists() else {}

    source_index = team_dir / "orchestrator-source-index.md"
    evidence = source_evidence(source_index)
    title = f"Team Presentation {unit_id}"
    if source_index.exists():
        m = re.search(r"^#\s+(.+)$", source_index.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)
        if m:
            title = m.group(1).strip()

    out = ["---", f'source: "[[{slug}]]"', f'unit_id: "{unit_id}"', f'title: "{title}"', "---", ""]
    for header, lanes in ASSEMBLY_ORDER:
        body = None
        for lane in lanes:
            sections = lane_sections.get(lane, {})
            if header in sections:
                body = sections[header]
                break
            for k, v in sections.items():
                if k.lower() == header.lower():
                    body = v
                    break
            if body is not None:
                break
        if body:
            body = body.strip()
            if header == "Author's Words":
                body = with_author_quotes(body, evidence, chapter_ref)
            elif header == "Relations":
                body = with_unit_evidence_corpus(body, evidence, chapter_ref)
            else:
                body = with_section_evidence(body, evidence, chapter_ref)
            out += [f"## {header}", "", body, ""]

    output = team_dir / f"team-{unit_id}-presentation.md"
    text = "\n".join(out).rstrip() + "\n"
    headers = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    dupes = sorted({h for h in headers if headers.count(h) > 1})
    if dupes:
        raise ValueError(f"duplicate headers in assembled presentation: {dupes}")
    output.write_text(text, encoding="utf-8")
    return output


def main() -> None:
    ap = argparse.ArgumentParser(description="Assemble named Domain Library specialist outputs")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--unit-id", required=True)
    ap.add_argument("--team-dir", required=True)
    ap.add_argument("--chapter-ref", required=True, help="Vault path of the unit's chapter file, without .md")
    args = ap.parse_args()
    out = assemble(Path(args.team_dir), args.slug, args.unit_id, args.chapter_ref)
    print(f"COMPLETED: Team Presentation {args.unit_id}. Output: {out}. STOP.")


if __name__ == "__main__":
    main()
