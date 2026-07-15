#!/usr/bin/env python3
"""Verify markdown image references in chapter files.

The Phase 2.4 gate requires every chapter image reference to be local and
resolvable. Remote/data refs can still be reported for diagnostics, but the
canonical runner forbids them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from domain_library.pipeline.common import write_json
from typing import Any

IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
REMOTE_PREFIXES = ("http://", "https://", "data:", "mailto:")


def _strip_ref(raw: str) -> str:
    raw = raw.strip().strip('"').strip("'")
    if " " in raw and not raw.startswith(("/", "./", "../")):
        raw = raw.split()[0]
    return raw


def verify(chapters_dir: Path, *, forbid_remote: bool = False) -> dict[str, Any]:
    files = sorted(p for p in chapters_dir.glob("*.md") if ".orig." not in p.name)
    refs = []
    missing = []
    remote = []
    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")
        for m in IMAGE_RE.finditer(text):
            raw = _strip_ref(m.group(1))
            if raw.startswith(REMOTE_PREFIXES):
                remote.append({"file": str(md), "ref": raw})
                continue
            fs_ref = raw.split("#", 1)[0].split("?", 1)[0]
            target = Path(fs_ref) if os.path.isabs(fs_ref) else (md.parent / fs_ref)
            item = {"file": str(md), "ref": raw, "resolved": str(target)}
            if target.exists() and target.is_file() and target.stat().st_size > 0:
                refs.append(item | {"exists": True})
            else:
                missing.append(item | {"exists": False})
    status = "PASS" if not missing and not (forbid_remote and remote) else "FAIL"
    return {
        "chapters_dir": str(chapters_dir),
        "chapter_files": len(files),
        "local_refs": len(refs) + len(missing),
        "remote_refs": len(remote),
        "resolved": len(refs),
        "missing": len(missing),
        "missing_refs": missing,
        "remote": remote,
        "forbid_remote": forbid_remote,
        "status": status,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify chapter markdown image refs resolve")
    ap.add_argument("--chapters-dir", required=True)
    ap.add_argument("--require-resolvable", action="store_true", help="exit 1 if any local image ref is missing")
    ap.add_argument("--forbid-remote", action="store_true", help="exit 1 if any remote/data image ref is present")
    ap.add_argument("--report", help="optional JSON report path")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = verify(Path(args.chapters_dir), forbid_remote=args.forbid_remote)
    if args.report:
        report_path = Path(args.report)
        write_json(report_path, result)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Image refs: {result['resolved']}/{result['local_refs']} local refs resolved; missing={result['missing']}; remote={result['remote_refs']}; status={result['status']}")
        for miss in result["missing_refs"][:20]:
            print(f"MISSING: {miss['file']} -> {miss['ref']} => {miss['resolved']}")
    if (args.require_resolvable and result["missing"]) or (args.forbid_remote and result["remote_refs"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
