#!/usr/bin/env python3
"""Shared plumbing for Domain Library pipeline phase runners.

Single source of truth for gate/state artifacts and the action log. Until
2026-06-12 every phase runner carried its own copy of these helpers; the
copies had already drifted (audit finding F7) — do not re-inline them.

`write_state` appends a contract-format line to log.md on every transition,
satisfying the llm-wiki rule "after every wiki write, update log.md".
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain_library.paths import default_wiki

# Shared slop/placeholder detector for phase 3.4/3.5/5 output validators. audit: ponytail-20260624
SLOP_RE = re.compile(r"\b(TODO|FIXME|PLACEHOLDER|Lorem ipsum)\b|\[(?:insert|TODO|PLACEHOLDER)[^\]]*\]|as an AI language model|I cannot access", re.IGNORECASE)
SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def validate_slug(slug: str) -> str:
    if not isinstance(slug, str) or len(slug) > 80 or not SLUG_RE.fullmatch(slug):
        raise ValueError("slug must be 1-80 lowercase letters/digits with internal hyphens")
    return slug


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as fh:
            temp_path = Path(fh.name)
            fh.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        return str(path)


def resolve_path(path_value: Any, wiki: Path) -> Path:
    path = Path(str(path_value))
    return path if path.is_absolute() else wiki / path


def extraction_root(wiki: Path, slug: str) -> Path:
    return wiki / "_meta" / "extractions" / validate_slug(slug)


def record_cost(
    wiki: Path,
    slug: str,
    phase: str,
    provider: str,
    model: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    usd: float | None = None,
    pages: int | None = None,
) -> Path:
    """Append one provider-usage event to a slug's single-writer ledger."""
    entry: dict[str, Any] = {
        "generated_at": utc_now(),
        "phase": phase,
        "provider": provider,
        "model": model,
    }
    for key, value in (("tokens_in", tokens_in), ("tokens_out", tokens_out), ("usd", usd), ("page_count_proxy", pages)):
        if value is not None:
            entry[key] = value
    path = extraction_root(wiki, slug) / "cost-ledger.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return path


# Canonical per-extraction artifact paths shared across phase runners. audit: ponytail-20260624
def schema_dir(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "schema"


def manifest_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "pipeline-run-manifest.json"


def verification_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "specialist-verification.json"


def confirmation_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "phase4-confirmation.json"


def confirmed_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "master-confirmed.json"


def gate_path(wiki: Path, slug: str, phase: str) -> Path:
    return extraction_root(wiki, slug) / "gates" / f"phase-{phase}.json"


def state_path(wiki: Path, slug: str) -> Path:
    return extraction_root(wiki, slug) / "pipeline-state.json"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_paths(paths: list[Path]) -> dict[str, str]:
    """Return deterministic content fingerprints keyed relative to their parent."""
    resolved = sorted({path.resolve() for path in paths}, key=str)
    if not resolved:
        return {}
    root = Path(os.path.commonpath(resolved))
    if root in resolved:
        root = root.parent

    fingerprints: dict[str, str] = {}
    for path in resolved:
        if path.is_file():
            fingerprints[rel(path, root)] = _sha256_file(path)
        elif path.is_dir():
            digest = hashlib.sha256()
            for child in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: str(item.relative_to(path))):
                digest.update(rel(child, path).encode())
                digest.update(b"\0")
                digest.update(_sha256_file(child).encode())
                digest.update(b"\n")
            fingerprints[rel(path, root)] = digest.hexdigest()
        else:
            raise FileNotFoundError(f"cannot fingerprint missing input: {path}")
    return fingerprints


def write_gate(
    wiki: Path,
    slug: str,
    phase: str,
    status: str,
    payload: dict[str, Any],
    inputs: list[Path] | None = None,
) -> Path:
    gate = {"phase": phase, "status": status, "slug": slug, "generated_at": utc_now(), **payload}
    if inputs is not None:
        gate["input_fingerprints"] = fingerprint_paths(inputs)
    path = gate_path(wiki, slug, phase)
    write_json(path, gate)
    return path




def load_state(wiki: Path, slug: str) -> dict[str, Any]:
    path = state_path(wiki, slug)
    if not path.exists():
        raise FileNotFoundError(f"pipeline-state.json not found: {path}")
    return read_json(path)


def append_log(wiki: Path, action: str, subject: str, actor: str) -> None:
    """Append one contract-format entry to log.md:
    `## [YYYY-MM-DD HH:MM] action | subject | actor` (see log.md header)."""
    log = wiki / "log.md"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"## [{stamp}] {action} | {subject} | {actor}\n"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(entry)


def write_state(
    wiki: Path,
    slug: str,
    status: str,
    current_phase: str,
    completed: list[str],
    gates: dict[str, str],
    runner: str,
) -> None:
    write_json(
        state_path(wiki, slug),
        {
            "slug": slug,
            "status": status,
            "current_phase": current_phase,
            "completed_phases": completed,
            "gates": gates,
            "updated_at": utc_now(),
            "runner": runner,
        },
    )
    append_log(wiki, "update", f"phase {current_phase} -> {status} ({slug})", runner)


def domain_config_path(wiki: Path) -> Path:
    return wiki / "_meta" / "config" / "domain.json"


def load_domain_config(wiki: Path) -> dict[str, Any]:
    path = domain_config_path(wiki)
    if not path.exists():
        # ponytail: fixture/scratch wikis fall back to the repo's shipped default config
        path = domain_config_path(default_wiki())
    if not path.exists():
        raise FileNotFoundError(f"domain config missing: {path}")
    data = read_json(path)
    for key in ("library_name", "tenant", "lanes"):
        if key not in data:
            raise ValueError(f"domain config missing key {key!r}: {path}")
    return data


def configured_lanes(wiki: Path) -> dict[str, dict[str, Any]]:
    config = load_domain_config(wiki)
    return {lane["id"]: lane for lane in config["lanes"]}
