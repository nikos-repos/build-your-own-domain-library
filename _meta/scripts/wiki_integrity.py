#!/usr/bin/env python3
"""Wiki link/embed integrity checker for the Domain Library vault.

Validates that every block embed `![[target#^anchor]]` and block link
`[[target#^anchor]]` resolves: the target must name exactly one note in the
vault and that note must contain the `^anchor`. Also detects the malformed
forms that previous pipeline generations produced:

- bracket-literal anchors copied from prompt templates: `![[source#^[id]]]`
- anchor-less block-id "note" links: `![[<slug>-chNN-NNNN]]`

Used as a library by library_phase5_pages.py / library_phase34_verify.py /
library_audit.py, and as a CLI for whole-wiki reports.

Resolution semantics (conservative subset of Obsidian's):
- target containing `/` -> vault-absolute path (with or without `.md`);
  a unique path-suffix match is reported as `suffix_match` (resolvable in
  Obsidian, but non-canonical — the repair tool rewrites these).
- bare target -> unique basename match; multiple matches -> `target_ambiguous`.

Statuses: ok | suffix_match | target_missing | target_ambiguous |
anchor_missing | malformed_bracket_anchor | malformed_anchorless_id
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from pipeline_common import write_json

# Well-formed block embed/link, optional |alias.
BLOCK_LINK_RE = re.compile(r"(!?)\[\[([^\]\[#|]+)#\^([A-Za-z0-9-]+)(?:\|([^\]]*))?\]\]")
# Prompt-template literal: anchor wrapped in square brackets (3 or 2 closers).
BRACKET_ANCHOR_RE = re.compile(r"(!?)\[\[([^\]\[#|]+)#\^\[([A-Za-z0-9-]+)\](\]\]|\])")
# A block ID used directly as a note name.
ANCHORLESS_ID_RE = re.compile(r"(!?)\[\[([a-z0-9-]+-ch\d+-\d+)\]\]")

SKIP_TOP_LEVEL = {"_legacy"}

DEAD_STATUSES = {
    "target_missing",
    "target_ambiguous",
    "anchor_missing",
    "malformed_bracket_anchor",
    "malformed_anchorless_id",
}


@dataclass
class VaultIndex:
    wiki: Path
    by_stem: dict[str, list[Path]] = field(default_factory=dict)
    _anchor_cache: dict[Path, set[str]] = field(default_factory=dict)
    _anchor_owner_cache: dict[str, list[Path]] | None = None

    def anchors(self, path: Path) -> set[str]:
        if path not in self._anchor_cache:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            self._anchor_cache[path] = set(re.findall(r"\^([A-Za-z0-9-]+)(?=\s|$)", text, flags=re.MULTILINE))
        return self._anchor_cache[path]

    def anchor_owners(self, anchor: str, under: Path | None = None) -> list[Path]:
        """All vault files containing ^anchor (optionally restricted to a subtree)."""
        if self._anchor_owner_cache is None:
            self._anchor_owner_cache = {}
            for paths in self.by_stem.values():
                for p in paths:
                    for a in self.anchors(p):
                        self._anchor_owner_cache.setdefault(a, []).append(p)
        owners = self._anchor_owner_cache.get(anchor, [])
        if under is not None:
            owners = [p for p in owners if under in p.parents or p == under]
        return owners


def build_vault_index(wiki: Path) -> VaultIndex:
    index = VaultIndex(wiki=wiki.resolve())
    for p in index.wiki.rglob("*.md"):
        rel_parts = p.relative_to(index.wiki).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if rel_parts and rel_parts[0] in SKIP_TOP_LEVEL:
            continue
        if "_legacy" in rel_parts:
            continue
        index.by_stem.setdefault(p.stem, []).append(p)
    return index


def vault_ref(path: Path, wiki: Path) -> str:
    """Canonical wikilink target for a vault file (vault-absolute, no .md)."""
    rel = path.resolve().relative_to(wiki.resolve())
    return str(rel).replace("\\", "/")[: -len(".md")] if str(rel).endswith(".md") else str(rel).replace("\\", "/")


def resolve_target(index: VaultIndex, target: str) -> tuple[str, Path | None]:
    """Resolve a wikilink target. Returns (status, path); status in
    ok | suffix_match | target_missing | target_ambiguous."""
    name = target.strip()
    if name.endswith(".md"):
        name = name[: -len(".md")]
    if "/" in name:
        exact = index.wiki / (name + ".md")
        if exact.exists():
            return "ok", exact
        suffix = name + ".md"
        matches = [
            p
            for paths in index.by_stem.values()
            for p in paths
            if str(p.relative_to(index.wiki)).replace("\\", "/").endswith(suffix)
        ]
        if len(matches) == 1:
            return "suffix_match", matches[0]
        return ("target_ambiguous", None) if matches else ("target_missing", None)
    matches = index.by_stem.get(Path(name).name, [])
    if len(matches) == 1:
        return "ok", matches[0]
    if len(matches) > 1:
        return "target_ambiguous", None
    return "target_missing", None


def check_text(index: VaultIndex, text: str) -> list[dict]:
    """All block-link findings in a markdown text."""
    findings: list[dict] = []
    consumed: set[tuple[int, int]] = set()

    for m in BRACKET_ANCHOR_RE.finditer(text):
        consumed.add((m.start(), m.end()))
        findings.append(
            {
                "raw": m.group(0),
                "embed": m.group(1) == "!",
                "target": m.group(2).strip(),
                "anchor": m.group(3),
                "status": "malformed_bracket_anchor",
                "resolved_path": "",
            }
        )
    for m in ANCHORLESS_ID_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        consumed.add((m.start(), m.end()))
        findings.append(
            {
                "raw": m.group(0),
                "embed": m.group(1) == "!",
                "target": m.group(2),
                "anchor": m.group(2),
                "status": "malformed_anchorless_id",
                "resolved_path": "",
            }
        )
    for m in BLOCK_LINK_RE.finditer(text):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        target, anchor = m.group(2).strip(), m.group(3)
        status, path = resolve_target(index, target)
        if status in {"ok", "suffix_match"} and path is not None and anchor not in index.anchors(path):
            status = "anchor_missing"
        findings.append(
            {
                "raw": m.group(0),
                "embed": m.group(1) == "!",
                "target": target,
                "anchor": anchor,
                "status": status,
                "resolved_path": vault_ref(path, index.wiki) if path else "",
            }
        )
    return findings


def check_files(index: VaultIndex, files: list[Path]) -> dict:
    rows = []
    totals: dict[str, int] = {}
    for f in sorted(files):
        text = f.read_text(encoding="utf-8", errors="replace")
        findings = check_text(index, text)
        dead = [x for x in findings if x["status"] in DEAD_STATUSES]
        for x in findings:
            totals[x["status"]] = totals.get(x["status"], 0) + 1
        rows.append(
            {
                "file": str(f.resolve().relative_to(index.wiki)),
                "links_checked": len(findings),
                "dead": len(dead),
                "dead_findings": dead,
            }
        )
    return {
        "wiki": str(index.wiki),
        "files_checked": len(rows),
        "files_with_dead_links": sum(1 for r in rows if r["dead"]),
        "links_checked": sum(r["links_checked"] for r in rows),
        "dead_links": sum(r["dead"] for r in rows),
        "status_totals": dict(sorted(totals.items())),
        "files": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Check block embed/link integrity across the wiki")
    ap.add_argument("--wiki", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--pages", nargs="*", default=["concepts/*.md"], help="Globs relative to wiki root")
    ap.add_argument("--json-out", help="Write full JSON report here")
    ap.add_argument("--fail-on-dead", action="store_true", help="Exit 2 if any dead link is found")
    args = ap.parse_args()

    wiki = Path(args.wiki).resolve()
    index = build_vault_index(wiki)
    files: list[Path] = []
    for pattern in args.pages:
        files.extend(p for p in wiki.glob(pattern) if p.suffix == ".md")
    if not files:
        raise SystemExit(f"no files matched {args.pages} under {wiki}")

    report = check_files(index, files)
    if args.json_out:
        out = Path(args.json_out)
        write_json(out, report)
    summary = {k: report[k] for k in ("files_checked", "files_with_dead_links", "links_checked", "dead_links", "status_totals")}
    print(json.dumps(summary, indent=2))
    if args.fail_on_dead and report["dead_links"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
