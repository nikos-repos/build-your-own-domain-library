"""Repository-root discovery shared by commands and pipeline modules."""
from __future__ import annotations

import os
from pathlib import Path


def repository_root(start: Path | None = None) -> Path:
    """Find the enclosing library root from a directory or file path."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    while True:
        if (current / "_meta" / "config" / "domain.json").is_file() and (current / "library.py").is_file():
            return current
        if current == current.parent:
            raise FileNotFoundError("not inside a Domain Library repository; pass --wiki")
        current = current.parent


def default_wiki() -> Path:
    """Use an explicit WIKI_PATH when present, otherwise the enclosing repo."""
    return repository_root(Path(os.environ["WIKI_PATH"]) if os.getenv("WIKI_PATH") else None)
