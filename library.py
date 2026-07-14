#!/usr/bin/env python3
"""Supported operator CLI for the Domain Library pipeline."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "_meta" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from pipeline_common import load_domain_config, validate_slug

NEXT = ROOT / "agents" / "orchestrator" / "skills" / "domain-library-run-and-operate" / "scripts" / "pipeline_next.py"


def run(*parts: str) -> int:
    return subprocess.run([sys.executable, *parts], cwd=ROOT).returncode


def env_value(name: str) -> str:
    if os.getenv(name):
        return os.environ[name].strip()
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name:
                return value.strip()
    return ""


def doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python 3.12+", sys.version_info[:2] >= (3, 12), sys.version.split()[0]))
    for module in ("pydantic", "requests", "pypdf", "yaml"):
        try:
            importlib.import_module(module)
            checks.append((f"import {module}", True, "ok"))
        except Exception as exc:
            checks.append((f"import {module}", False, str(exc)))
    try:
        config = load_domain_config(ROOT)
        checks.append(("domain configuration", bool(config["lanes"]), f"{len(config['lanes'])} lane(s)"))
    except Exception as exc:
        checks.append(("domain configuration", False, str(exc)))
    override = None
    try:
        import library_phase33_dispatch as dispatch
        override = os.environ.pop("AGENT_PROFILE_DIR", None)
        dispatch._load_lanes(ROOT)
        profiles = dispatch.validate_agent_profiles()
        checks.append(("agent profiles", True, f"{len(profiles)} valid"))
    except Exception as exc:
        checks.append(("agent profiles", False, str(exc)))
    finally:
        if override is not None:
            os.environ["AGENT_PROFILE_DIR"] = override
    required = [SCRIPTS / "library_phase1_ocr.py", SCRIPTS / "library_audit.py", NEXT, ROOT / "raw" / "papers", ROOT / "_meta" / "extractions"]
    checks.append(("required files", all(path.exists() for path in required), "present"))
    ignored = subprocess.run(["git", "check-ignore", "--quiet", ".env"], cwd=ROOT).returncode == 0
    checks.append((".env ignored by Git", ignored, "yes" if ignored else "no"))
    if not args.no_secrets:
        key = env_value("ZHIPU_API_KEY")
        checks.append(("ZHIPU_API_KEY", bool(key and key != "replace_me"), "configured" if key and key != "replace_me" else "missing/placeholder"))
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}")
    if args.full and all(ok for _, ok, _ in checks):
        return run(str(SCRIPTS / "library_pipeline_test_suite.py"))
    return 0 if all(ok for _, ok, _ in checks) else 2


def start(args: argparse.Namespace) -> int:
    slug = validate_slug(args.slug)
    command = [str(SCRIPTS / "library_phase1_ocr.py"), "--slug", slug, "--pdf", args.pdf]
    for flag in ("title", "author"):
        value = getattr(args, flag)
        if value:
            command.extend([f"--{flag}", value])
    return run(*command)


def next_command(args: argparse.Namespace) -> int:
    return run(str(NEXT), "--slug", validate_slug(args.slug))


def status(args: argparse.Namespace) -> int:
    command = [str(NEXT), "--json"]
    command += ["--slug", validate_slug(args.slug)] if args.slug else ["--all"]
    return run(*command)


def restart(args: argparse.Namespace) -> int:
    slug = validate_slug(args.slug)
    if not args.yes:
        print("refusing destructive restart without --yes", file=sys.stderr)
        return 2
    for path in (ROOT / "raw" / "papers" / slug, ROOT / "_meta" / "extractions" / slug):
        shutil.rmtree(path, ignore_errors=True)
    print(json.dumps({"status": "RESET", "slug": slug}))
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor")
    p.add_argument("--full", action="store_true")
    p.add_argument("--no-secrets", action="store_true", help="CI mode: do not require an OCR key")
    p.set_defaults(func=doctor)
    p = sub.add_parser("start")
    p.add_argument("--pdf", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--title", default="")
    p.add_argument("--author", default="")
    p.set_defaults(func=start)
    p = sub.add_parser("next")
    p.add_argument("--slug", required=True)
    p.set_defaults(func=next_command)
    p = sub.add_parser("status")
    p.add_argument("--slug")
    p.set_defaults(func=status)
    p = sub.add_parser("restart", help="delete one ingest's generated state so a different PDF can reuse its slug")
    p.add_argument("--slug", required=True)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=restart)
    return ap


if __name__ == "__main__":
    args = parser().parse_args()
    try:
        raise SystemExit(args.func(args))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
