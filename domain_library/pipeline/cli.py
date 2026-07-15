"""Shared command-line setup for pipeline phase runners."""
from __future__ import annotations

import argparse
from pathlib import Path

from domain_library.paths import default_wiki


def pipeline_parser(description: str, *, default: Path | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--wiki", default=str(default or default_wiki()), help="Library root")
    return parser
